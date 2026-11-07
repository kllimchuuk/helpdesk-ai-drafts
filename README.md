# Helpdesk AI Drafts

A backend service that receives helpdesk tickets by webhook, finds relevant knowledge-base articles, asks an LLM for a draft reply, lets an operator approve or reject it in a web UI, and sends approved replies back through the helpdesk API.

This is a test task, built with AI coding agents. Read how the work is organised in [`CLAUDE.md`](CLAUDE.md), what the service must do in [`docs/SPEC.md`](docs/SPEC.md), and why each choice was made in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

Work proceeds in slices (SPEC §13). Done so far: project skeleton with `/health`, Docker Compose and a placeholder page; the `ticket_events` schema with Alembic migrations; the idempotent webhook `POST /webhooks/helpdesk`; `GET /api/stats`; the knowledge base (8 Ukrainian articles, search by text, `GET /api/kb/{slug}`); the LLM gateway (rate limit, daily cap, keyless mode); the generation worker that turns every new ticket into a draft; the operator UI to approve or reject drafts; and the send path that delivers approved replies. The mock helpdesk and the simulator are still to come, so this file will grow with them.

## Run

Requirements: Docker with Compose. No configuration is needed. Compose starts PostgreSQL, the backend (it runs the migrations and loads the KB), the `worker` that drafts replies, and nginx with the operator UI.

```bash
docker compose up --build
```

| What | Where |
|---|---|
| Health check | http://localhost:8000/health (backend) and http://localhost:8080/health (through nginx) |
| Operator UI (login `operator` / `operator`) | http://localhost:8080 |
| Public KB article | http://localhost:8080/kb/reset-password |
| PostgreSQL | `127.0.0.1:5434` (change with `DB_HOST_PORT`) |

Try the webhook. The loop sends the same event twice, and the second answer is `duplicate` (if you run it again on the same database volume both answers are `duplicate`):

```bash
for attempt in 1 2; do
  curl -s -X POST http://localhost:8080/webhooks/helpdesk -H 'content-type: application/json' -d '{
    "event_id": "evt_8f2a",
    "ticket_id": "T-1042",
    "customer_email": "user@example.com",
    "message": "Не можу експортувати звіт у PDF",
    "reply_url": "https://helpdesk.example.com/tickets/T-1042/replies"
  }'
  echo
done
```

A new event is answered with `{"status":"accepted"}`, a repeated one with `{"status":"duplicate"}`. Then look at the counts:

```bash
curl -s http://localhost:8080/api/stats
```

The ticket starts as `received`. Without an API key the worker sends a real request, discards the answer and stores the static reply after 5 to 30 seconds, so `/api/stats` soon shows it as `draft_ready`. Follow the worker with `docker compose logs -f worker`.

Stop with `docker compose down` (add `-v` to delete the database volume).

## Knowledge base

The articles are Markdown files in `backend/content/knowledge_base/` about a fictional product (Vistara), written with Claude as the task asks. Each file starts with front matter and its name is the slug:

```
---
slug: reset-password
title: Відновлення пароля
---
Article text...
```

The backend container loads the files into PostgreSQL every time it starts, so to add or change an article edit the file and run `docker compose up -d --build backend`. Read one with `curl -s http://localhost:8080/api/kb/reset-password`. Search by ticket text is done inside the service (PostgreSQL trigram similarity plus full-text rank), and the worker puts the matching articles into the prompt and links them under the draft; see `docs/DECISIONS.md` for how it was tuned and how well it works. If an article file is invalid the loader logs a warning and the service keeps running with the articles already stored.

## LLM calls, rate limit and keyless mode

Drafts are written by Claude Haiku 5.5 through the official SDK. Set `ANTHROPIC_API_KEY` in a `.env` next to `docker-compose.yml` to use a real key. Every call to the provider goes through one gate stored in PostgreSQL (the `llm_calls` table), so the limit holds for the whole service whatever the number of workers: at most `LLM_RATE_LIMIT_PER_MINUTE` calls in any 60 seconds (default 55, never above 60), and at most `LLM_DAILY_CALL_CAP` real calls per UTC day (default 500), after which the service behaves as if it had no key until midnight UTC. The SDK's own retries are switched off because a retry the gate never counted would break the limit.

Without `ANTHROPIC_API_KEY` (the default, so `docker compose up` needs no configuration) the service still sends a real request with a placeholder credential, ignores the answer, waits until a random 5 to 30 seconds have passed and uses a fixed Ukrainian reply marked as static. Nothing else in the pipeline can tell the difference; the draft is only marked `draft_is_static`. Tests never touch the network.

## Generation worker

`python -m workers` (the `worker` service) claims new tickets from PostgreSQL with `FOR UPDATE SKIP LOCKED`, finds KB articles, asks the model for a draft and stores it as `draft_ready`. Each claim holds a 120 s lease that a heartbeat renews every 40 s; if a worker dies, the lease expires and another worker takes the ticket. Transient failures are retried with exponential backoff up to 5 attempts, a refusal or a rejected request goes to `generation_failed` with the reason in `last_error`. Any number of workers can run against the same database (`docker compose up --scale worker=3`); `LLM_CONCURRENCY` (default 20) sets the tickets in flight per worker. Details in SPEC §7-§8 and DECISIONS (S4).

## Operator UI

Static pages in `frontend/` (Bootstrap from a CDN, plain JavaScript modules, no build step) served by nginx, which also proxies `/api`, `/webhooks` and `/health` to the backend. The ticket list refreshes every 5 seconds and filters by status; a ticket page shows the customer message, the draft, its KB sources, the low-confidence and static flags and the last error, with **Approve** and **Reject** while the draft is ready. Approving twice, or two operators at once, cannot approve a reply twice: the change is one conditional `UPDATE`, and the loser gets `409`.

The operator API uses Basic Auth (`OPERATOR_USER`, `OPERATOR_PASSWORD`; the browser shows its own login prompt). The defaults are refused when `APP_ENV=production`. Approve and reject also require the header `X-Requested-By: operator-ui` and the content type `application/json`, so another site cannot post a form with the browser's cached credentials. Customer and model text is always inserted as text, never as HTML, and nginx sends a Content-Security-Policy that allows no inline or third-party scripts. Customers open KB links at `/kb/<slug>`, a public page.

Try it from the command line:

```bash
curl -s -u operator:operator 'http://localhost:8080/api/tickets?status=draft_ready'
curl -s -u operator:operator -X POST -H 'X-Requested-By: operator-ui' \
  -H 'Content-Type: application/json' -d '{}' \
  http://localhost:8080/api/tickets/<id>/approve
```

## Sending replies

The worker also sends approved replies to the ticket's `reply_url` with the header `Idempotency-Key: <ticket id>`. Only `201` counts as delivered. A failure that certainly happened before the request left (connection refused, unknown host) or a `5xx`, `408` or `429` is retried with backoff up to 8 attempts, then `send_failed`; another `3xx` or `4xx` fails at once. When the request may have reached the helpdesk (a timeout after sending, a dropped connection, a worker that died mid-send, another `2xx`), the ticket becomes `send_unknown` and is never resent automatically: the operator checks the helpdesk and clicks **Mark delivered** or **Resend**. This trades one extra click for never sending a customer the same reply twice. `SEND_RETRY_AMBIGUOUS=true` retries those cases too, for receivers that honour the idempotency key.

`reply_url` comes from the webhook body, so it is untrusted: the host is resolved once, every address must be public (unless the host is in `REPLY_URL_ALLOWED_HOSTS`), the request goes to that checked address with the original `Host` header and TLS name, and redirects are never followed.

## Develop

Requirements: [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d db
cd backend
uv sync
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5434/helpdesk
uv run alembic upgrade head
uv run uvicorn main:app --reload --app-dir src
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests need the compose `db` service; they create and drop their own `helpdesk_test` database and never touch `helpdesk`. `DATABASE_URL` above points the backend at the published port of the compose database (inside compose the host is `db`).

Environment variables are listed in [`.env.example`](.env.example); all of them are optional.

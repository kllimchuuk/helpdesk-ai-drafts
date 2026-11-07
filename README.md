# Helpdesk AI Drafts

A backend service that receives helpdesk tickets by webhook, finds relevant knowledge-base articles, asks an LLM for a draft reply, lets an operator approve or reject it in a web UI, and sends approved replies back through the helpdesk API.

This is a test task, built with AI coding agents. Read how the work is organised in [`CLAUDE.md`](CLAUDE.md), what the service must do in [`docs/SPEC.md`](docs/SPEC.md), and why each choice was made in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

All slices S0-S7 are built and merged (SPEC §13): the idempotent webhook `POST /webhooks/helpdesk` and `GET /api/stats`; the knowledge base (8 Ukrainian articles, search by text, `GET /api/kb/{slug}`); the LLM gateway (rate limit, daily cap, keyless mode); the generation worker; the operator UI to approve or reject drafts; the send path with `send_unknown`, **Mark delivered** and **Resend**; the mock helpdesk with chaos modes; and the load simulator. The production stack is `docker-compose.prod.yml` (see "Deploy on a VDS"). The measured runs are in [`docs/REPORT.md`](docs/REPORT.md). Cut on purpose: JSON logs and HTTPS (DECISIONS, S9).

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

## Mock helpdesk

`tools/mock_helpdesk` (the `mock-helpdesk` service) receives replies at `POST /tickets/{id}/replies`, answers `201` and counts deliveries per `Idempotency-Key`. Put a `reply_url` such as `http://mock-helpdesk:8000/tickets/T-1042/replies` in a webhook to send there; `mock-helpdesk` is the only host allowed to resolve to a private address. Read the counts with `curl -s http://127.0.0.1:8090/_debug/deliveries` and clear them with `curl -s -X POST http://127.0.0.1:8090/_debug/reset`.

Chaos comes from the root `.env`: `FAIL_5XX_RATE`, `TIMEOUT_RATE`, `HANG_AFTER_STORE_RATE` (stores the reply, then never answers in time) and `HONOR_IDEMPOTENCY_KEY=false` (stores every copy, so a duplicate send would show up as `duplicates`). Restart the service after changing them: `docker compose up -d mock-helpdesk`.

## Simulator

`tools/simulator` sends webhooks and measures the pipeline (SPEC §11). It runs as a compose service in the `tools` profile:

```bash
docker compose run --rm simulator --events 500 --duration 600 --approve
```

Options: `--events`, `--duration` (seconds), `--duplicate-rate` and `--concurrent-duplicates` (that share of events is sent as several simultaneous copies), `--approve` (approve this run's drafts so they are sent), `--seed`, `--json <file>` (or `--json -`, the form that works inside the container: the JSON goes to stdout and the readable text to stderr, so it can be piped to `jq`). It prints webhook latency, the answers (`accepted` exactly once per event), the time until the queue drained, final status counts and the deliveries counted by the mock, and exits with status 1 if an event was accepted twice or never, the queue did not drain (unless `--drain-timeout 0`), the mock stored a reply twice or its counts are missing. Transient errors while polling the backend are counted by kind and the run continues; a `401` or `403` from the operator API (wrong `OPERATOR_PASSWORD`) stops it at once. It resets the mock's counts, so use a fresh database (`docker compose down -v` first) for numbers you want to keep. Results of the measured run are in [`docs/REPORT.md`](docs/REPORT.md).

## Deploy on a VDS

`docker-compose.prod.yml` is the production stack: the same services, but `APP_ENV=production`, no default secrets (compose refuses to start until they are set), only nginx published (port 80), the database and backend reachable inside the compose network only, and `restart: unless-stopped`.

1. Create an Ubuntu server, add your SSH key, note the public IP.
2. Install Docker: `curl -fsSL https://get.docker.com | sh`
3. Clone the repository and create the settings:
   ```bash
   git clone <repo-url> && cd helpdesk-ai-drafts
   cp .env.example .env
   # set DB_PASSWORD (letters and digits), OPERATOR_USER, OPERATOR_PASSWORD (not the
   # defaults) and PUBLIC_BASE_URL=http://<server-ip>; optionally ANTHROPIC_API_KEY
   # together with LLM_DAILY_CALL_CAP
   ```
4. Start it and open port 80:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ufw allow 80          # or open port 80 in the Hetzner firewall
   ```
5. Visit `http://<server-ip>/` (operator login from `.env`) and check `http://<server-ip>/health`.

The stack runs without `ANTHROPIC_API_KEY` in keyless mode (I8). The public webhook is `POST http://<server-ip>/webhooks/helpdesk`; replies go to the `reply_url` of each event, and a `reply_url` that resolves to a private address is refused. To try the full loop on the server, start the demo receiver with `REPLY_URL_ALLOWED_HOSTS=mock-helpdesk` in `.env` and `docker compose -f docker-compose.prod.yml --profile demo up -d`, and use `http://mock-helpdesk:8000/tickets/<id>/replies` as `reply_url`.

nginx limits the public endpoints per client address: the webhook to 10 requests a second (burst 20) and the operator API to 20 a second (burst 40), answering `429` above that, and refuses bodies above 256 KB (`413`). A helpdesk that retries on a non-2xx answer loses nothing. There is no TLS: the operator's Basic Auth password travels in clear text over HTTP (DECISIONS, S9). Use a strong password, and put the stack behind HTTPS before real use.

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
cd ../tools && uv sync && uv run pytest && uv run ruff check .
```

The tests need the compose `db` service; they create and drop their own `helpdesk_test` database and never touch `helpdesk`. `DATABASE_URL` above points the backend at the published port of the compose database (inside compose the host is `db`).

Environment variables are listed in [`.env.example`](.env.example); all of them are optional.

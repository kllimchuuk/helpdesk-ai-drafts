# Helpdesk AI Drafts

A backend service that receives helpdesk tickets by webhook, finds relevant knowledge-base articles, asks an LLM for a draft reply, lets an operator approve or reject it in a web UI, and sends approved replies back through the helpdesk API.

This is a test task, built with AI coding agents. Read how the work is organised in [`CLAUDE.md`](CLAUDE.md), what the service must do in [`docs/SPEC.md`](docs/SPEC.md), and why each choice was made in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

Work proceeds in slices (SPEC §13). Done so far: project skeleton with `/health`, Docker Compose and a placeholder page; the `ticket_events` schema with Alembic migrations; the idempotent webhook `POST /webhooks/helpdesk`; and `GET /api/stats`. The KB search, LLM pipeline, workers, operator UI, mock helpdesk and simulator are still to come, so this file will grow with them.

## Run

Requirements: Docker with Compose. No configuration is needed.

```bash
docker compose up --build
```

| What | Where |
|---|---|
| Health check | http://localhost:8000/health (backend) and http://localhost:8080/health (through nginx) |
| Placeholder page | http://localhost:8080 |
| PostgreSQL | `127.0.0.1:5434` (change with `DB_HOST_PORT`) |

Try the webhook (the second call is reported as a duplicate):

```bash
curl -s -X POST http://localhost:8080/webhooks/helpdesk -H 'content-type: application/json' -d '{
  "event_id": "evt_8f2a",
  "ticket_id": "T-1042",
  "customer_email": "user@example.com",
  "message": "Не можу експортувати звіт у PDF",
  "reply_url": "https://helpdesk.example.com/tickets/T-1042/replies"
}'
curl -s http://localhost:8080/api/stats
```

Stop with `docker compose down` (add `-v` to delete the database volume).

## Develop

Requirements: [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload --app-dir src
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests need the compose `db` service; they create and drop their own `helpdesk_test` database and never touch `helpdesk`. When running the backend on your machine set `DATABASE_URL` to the published port (see `.env.example`).

Environment variables are listed in [`.env.example`](.env.example); all of them are optional.

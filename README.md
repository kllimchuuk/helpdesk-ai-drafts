# Helpdesk AI Drafts

A backend service that receives helpdesk tickets by webhook, finds relevant knowledge-base articles, asks an LLM for a draft reply, lets an operator approve or reject it in a web UI, and sends approved replies back through the helpdesk API.

This is a test task, built with AI coding agents. Read how the work is organised in [`CLAUDE.md`](CLAUDE.md), what the service must do in [`docs/SPEC.md`](docs/SPEC.md), and why each choice was made in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

Work proceeds in slices (SPEC §13). Done so far: project skeleton with `/health`, Docker Compose and a placeholder page; the `ticket_events` schema with Alembic migrations; the idempotent webhook `POST /webhooks/helpdesk`; `GET /api/stats`; and the knowledge base (8 Ukrainian articles, search by text, `GET /api/kb/{slug}`). The LLM pipeline, workers, operator UI, mock helpdesk and simulator are still to come, so this file will grow with them.

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

The backend container loads the files into PostgreSQL every time it starts, so to add or change an article edit the file and run `docker compose up -d --build backend`. Read one with `curl -s http://localhost:8080/api/kb/reset-password`. Search by ticket text is done inside the service (PostgreSQL trigram similarity plus full-text rank) and will be used when drafts are generated; see `docs/DECISIONS.md` for how it was tuned and how well it works. If an article file is invalid the loader logs a warning and the service keeps running with the articles already stored.

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

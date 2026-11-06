# Helpdesk AI Drafts

A backend service that receives helpdesk tickets by webhook, finds relevant knowledge-base articles, asks an LLM for a draft reply, lets an operator approve or reject it in a web UI, and sends approved replies back through the helpdesk API.

This is a test task, built with AI coding agents. Read how the work is organised in [`CLAUDE.md`](CLAUDE.md), what the service must do in [`docs/SPEC.md`](docs/SPEC.md), and why each choice was made in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Status

Work proceeds in slices (SPEC §13). Done so far: project skeleton with `/health`, Docker Compose and a placeholder page. The webhook, queue, LLM pipeline, operator UI, mock helpdesk and simulator are still to come, so this file will grow with them.

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

Stop with `docker compose down` (add `-v` to delete the database volume).

## Develop

Requirements: [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Environment variables are listed in [`.env.example`](.env.example); all of them are optional.

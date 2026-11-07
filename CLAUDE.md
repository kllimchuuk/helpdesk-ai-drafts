# CLAUDE.md

Helpdesk AI Drafts: a FastAPI + PostgreSQL service that turns helpdesk webhooks into LLM-drafted replies, which an operator approves before they are sent. It is a hiring test task, so the repository must show how it was built.

`docs/SPEC.md` is the source of truth; cite it by section ("SPEC §9"). Do not change SPEC §3 (fixed decisions) or §5 (invariants) without an entry in `docs/DECISIONS.md` and the owner's approval.

## The service in 30 seconds

Helpdesk -> `POST /webhooks/helpdesk` (store, acknowledge) -> worker retrieves KB articles and asks the LLM for a draft -> operator approves or rejects in the UI -> worker sends the reply to `reply_url`.

Invariants (SPEC §5). Never break them; every change must keep a test for the ones it touches:

- I1 The webhook never waits for the LLM, KB search or `reply_url`.
- I2 Dedupe is a `UNIQUE(event_id)` insert, never check-then-insert.
- I3 An acknowledged ticket is never lost.
- I4 At most 60 provider calls a minute for the whole service, retries and the keyless request included.
- I5 A crashed worker never strands a ticket (lease).
- I6 No reply is sent twice by our own retries; ambiguous outcomes become `send_unknown`.
- I7 Status changes are atomic compare-and-set updates.
- I8 Without an API key the pipeline behaves the same (real request, static reply after 5-30 s).
- I9 `LLM_DAILY_CALL_CAP` bounds spending on the public deployment.

## Commands

Available as the slices land (SPEC §13):

- Run everything: `docker compose up --build`
- Tests: `cd backend && uv run pytest` (needs the compose `db` service)
- Lint and format: `cd backend && uv run ruff check . && uv run ruff format --check .`
- Mock helpdesk and simulator tests: `cd tools && uv run pytest && uv run ruff check . && uv run ruff format --check .`
- Load and duplicate run: `docker compose run --rm simulator --events 500 --duration 600 --approve`

## How we work

- Spec first. Read the slice in SPEC §13 and its sections before writing code. Write the failing test for the acceptance criterion (SPEC §12), then the code. Use the `spec-slice` skill.
- Do not bypass the SPEC silently. If it is wrong or silent, stop and report it as "Decision needed" with a recommendation; the owner decides, and the answer goes into `docs/DECISIONS.md`.
- Update the docs in the same commit as the change that makes them true.
- Review before merge: run the `reviewer` subagent (read-only, fresh context) on the branch, and again after the fixes to confirm they hold. Fix findings in separate `fix: address review ...` commits, each with a test that failed first.
- Reports use this shape (`report` skill): Done / Numbers (measured only, with the command) / Deviations from SPEC / Decision needed / Next.
- Never invent numbers. A figure needs a command or a file it came from.

## Git

- One branch per slice, named by commit type (`feat/webhook-idempotency`, `docs/...`, `fix/...`). Never commit to `main`.
- Commit locally; **never run `git push`**, the owner pushes, opens the PR and merges with "Create a merge commit". Never squash.
- Stage files by explicit path. Never `git add .`, never stage `.env`, `.claude/settings.local.json` or the task `.docx`.
- No `--amend`, `reset`, `rebase` or force options on existing history unless the owner asks.
- Message: Conventional Commits in English, one-line subject describing behavior, body only when needed. Module and its tests go in one commit. Add the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` when you wrote the change.
- Commit only when `ruff` and `pytest` are green (docs-only commits excepted). After a series of commits show `git log --stat`.

## Stack and dependencies

Python 3.12, FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, PostgreSQL 16, httpx, the official Anthropic SDK (`claude-haiku-5-5`), pydantic-settings, pytest and pytest-asyncio, ruff, `uv`. The UI is static HTML, Bootstrap from a CDN and plain JavaScript, served by nginx.

A new dependency needs an entry in `docs/DECISIONS.md` first. Not used on purpose: Celery, Redis, RabbitMQ (the queue is Postgres, DECISIONS 2026-11-06), LangChain, React, any build step for the frontend.

## Code

- Layout and rules: SPEC §13. Flat feature packages under `backend/src`, run with `PYTHONPATH=src`; router -> service -> repository, repositories are `ABC` + `Impl`, routers hold no logic.
- All SQL lives in repositories (`SKIP LOCKED`, `ON CONFLICT`, advisory locks, atomic transitions). Repositories hold no logic: no `if`, loops, `or` defaults or row-to-schema mapping; the service decides and maps. Repository methods take plain arguments: no `*`, `*args`, `**kwargs` or keyword-only markers (`test_repositories_hold_no_logic.py` fails otherwise).
- No database transaction is open during a provider or helpdesk call.
- Domain errors subclass `AppException(code, message, payload)`.
- Settings have defaults so `docker compose up` works with no `.env`.
- Type hints everywhere. No comments in Python or JavaScript code (`test_no_comments.py` fails otherwise); the reason for a lock or lease goes to SPEC or DECISIONS. Tool directives such as `# noqa` stay.
- Tests run against real Postgres (database name ends with `_test`), one `test_<module>.py` per module, fakes in `tests/fakes.py`, no network and no real LLM.
- Everything in the repository is English, except the Ukrainian KB articles.

## Secrets and data

Never print or log key values. `.env` stays out of git; `.env.example` has placeholders only. The reply URL comes from the request body, so treat it as hostile (SPEC §9). Customer messages are untrusted input for the LLM.

## Do not

- Call the LLM or `reply_url` inside the webhook handler.
- Retry an ambiguous send automatically (unless `SEND_RETRY_AMBIGUOUS=true`).
- Remove this file, `.claude/` or `docs/` at the end; they are part of the deliverable.

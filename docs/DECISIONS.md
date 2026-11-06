# Decisions

Each entry has a date, the decision, why, and what changed. The owner decides; proposals made by the AI agent are marked **recommendation** and apply once confirmed. Open questions live in `docs/SPEC.md` §14. Newest entries go at the bottom.

## 2026-11-06 - Stack and infrastructure

Basis: owner's confirmation in the planning session; SPEC §3.

1. **FastAPI instead of Django.**
   Why: the workload is mostly waiting (about 18 concurrent LLM calls, outbound HTTP), which fits async Python naturally. We need no admin site or built-in auth, the two things Django would give for free. The cost is assembling SQLAlchemy, Alembic and the UI ourselves.
   Changed: SPEC §3.
2. **Postgres as the queue instead of Redis or RabbitMQ.**
   Why: the event and the job are one row written in one transaction, so there is no dual write (insert to the database, then publish to a broker) and no window in which an acknowledged ticket can be lost. It removes two services from `docker compose up`, and queue state is plain SQL. The cost is polling (about 1 s) and a ceiling in the low thousands of jobs per second, far above this load (at most about 1 per second).
   Switch to RabbitMQ or Redis when: several services consume the same events, throughput outgrows one Postgres, or we need priorities and dead-letter routing out of the box.
   Changed: SPEC §3, §7.
3. **Claude Haiku 5.5 at low effort.**
   Why: short drafts from supplied context do not need a larger model; roughly $0.0007 per draft (estimate from list prices) against about $0.014 for Sonnet. Thinking is on by default for this model and bills as output, so effort is set explicitly.
   Changed: SPEC §3, §8.
4. **Hetzner VPS with Docker Compose and Caddy.**
   Why: the server runs the same `docker compose up` as a laptop, nothing sleeps (a cold start would break the 2 s webhook limit, as on free PaaS tiers), and Caddy provides HTTPS without manual certificates. `<ip>.sslip.io` serves as the hostname when no domain is available.
   Changed: SPEC §3, §13.
5. **`uv` for dependencies.**
   Why: a lock file and `uv sync --frozen` give reproducible builds and a cached dependency layer in Docker.
   Changed: SPEC §3.
6. **Original task file stays out of git; the repository is private for now.**
   Why: the task document is the hiring company's material. `docs/*.docx` is in `.gitignore`; its requirements are restated in SPEC. The repository becomes public later at the owner's choice.
   Changed: `.gitignore`, SPEC §3.

## 2026-11-06 - Language and process

Basis: owner's confirmation.

1. **English for everything in the repository** (docs, agent config, code, comments, commits, LLM system prompt). KB articles are Ukrainian because the sample tickets are Ukrainian, and the model replies in the customer's language.
   Why: professional convention and the vacancy requires English.
   Changed: SPEC §3.
2. **The agent commits locally, the owner pushes.**
   Why: the commit history is reviewed as is, without squash, so the owner must check it before publication. Local commits are reversible, a push to GitHub is not. Commits follow Conventional Commits in English and carry `Co-Authored-By: Claude` only where the agent wrote the change.
   Changed: `CLAUDE.md` working rules.
3. **Agent skills are project-specific.** The planned set is `spec-slice`, `invariants-check` and `report`, plus a read-only `reviewer` subagent. Generic skills (SOLID, DRY and similar) are not copied in: the model already knows them, their broad triggers fire on every task, and they carry nothing about this service.
   Changed: SPEC §13.
4. **One branch per slice, pull request into `main`, merged with a merge commit.**
   Why: the task wants the history as is, without squash, and a branch per slice shows the work step by step, as in the owner's `cadence` project. The pull request description doubles as the stage report. Squash and rebase-merge are not used; force push is forbidden.
   Changed: SPEC §13, `CLAUDE.md`.

## 2026-11-06 - Failure semantics

Basis: owner's confirmation of the recommendation; SPEC §5, §8, §9.

1. **Ambiguous send outcomes become `send_unknown` and are not retried automatically.**
   Context: a read timeout after the request is sent may mean the helpdesk stored the reply. The task forbids delivering the same reply twice, and the contract has no way to ask whether a reply exists. Retrying with an `Idempotency-Key` only helps when the receiver honors it, which an unknown reviewer mock may not.
   Why: retry automatically only when delivery definitely did not happen (connection error before sending, HTTP 5xx). Anything else waits for the operator (**Mark delivered** or **Resend**). The cost is manual work in proportion to the timeout rate (about 25 of 500 tickets at 5%); the benefit is zero service-caused duplicates. `SEND_RETRY_AMBIGUOUS=true` restores automatic retry for receivers known to be idempotent.
   Changed: SPEC §5 (I6), §6, §9, §10, §11, §12.
2. **A daily cap on provider calls (`LLM_DAILY_CALL_CAP`).**
   Why: the webhook is public and every ticket triggers a paid call. The rate limit bounds speed, not total spend (up to about $55 a day at 55 calls a minute). After the cap the service uses the keyless static path, which also exercises that mode.
   Changed: SPEC §5 (I9), §8, §14.

## 2026-11-06 - Code structure and UI

Basis: owner's decision after the agent studied the `cadence` project; SPEC §3, §10, §13.

1. **Feature packages in the style of `cadence`, not layers.** Each feature has models, repository, service, schemas, exceptions and, where needed, a router; shared pieces live in `core/`. The first proposal (top-level `api/`, `services/`, `repositories/` folders) was rejected.
   Why: the owner already works this way, so the code stays familiar and consistent across projects, and a feature can be read in one folder.
   Changed: SPEC §13.
2. **Repositories are an `ABC` plus an `Impl`.** The agent first proposed skipping the abstract class because there is one implementation.
   Why: the owner's convention outweighs the saving, and the cost is small.
   Changed: SPEC §13 rule 2.
3. **`ruff` for lint and format, `pytest` for tests.**
   Why: one tool instead of black plus flake8; same checks, simpler CI-free workflow.
   Changed: SPEC §3.
4. **Comments only where the reason is not obvious** (why a lock, a lease or a limiter exists). Everything else is expressed by names.
   Changed: SPEC §13 rule 7, `CLAUDE.md`.
5. **Separate `frontend/` of static files (HTML, Bootstrap from a CDN, plain JavaScript) over a JSON API, served by nginx; no Node build and no React.** The task asks for a basic interface "without attention to design" and the role is back-end focused, so the UI stays minimal. It is still separate from `backend/`, as in `cadence`: the API-first design shows REST skills, and the UI can be replaced (for example by React) without touching the backend. The agent first recommended server-rendered Jinja2 pages for speed (about one hour less); the owner preferred the separation.
   Cost: one more container (nginx proxying `/api`, `/webhooks`, `/health`, so no CORS) and about one extra hour. If time runs short, the UI shrinks to two pages.
   Changed: SPEC §3, §4, §10, §13.
6. **`mock_helpdesk` and `simulator` live in `tools/` with their own Dockerfile and dependencies.** They are test equipment, not service code: the mock must run as a container in `docker compose up`, the simulator via `docker compose run`. They never import from `backend`, which proves the HTTP contract in the task is complete. The alternative was to ship them inside the backend image (fewer files, but test code in the production image).
   Changed: SPEC §11, §13.

## 2026-11-06 - Design choices by the agent

**Recommendation**, confirmed when the owner approves SPEC.

1. **One table row per helpdesk event, doubling as the job.** `ticket_id` is not unique because follow-up events can exist. Why: simplest model that gives atomic dedupe through `UNIQUE(event_id)`. Changed: SPEC §6.
2. **Retrieval with `pg_trgm` and full-text search in the `simple` configuration, no embeddings.** Why: Postgres has no built-in Ukrainian text-search configuration, trigram similarity tolerates word endings, and the service must work with no API key. Changed: SPEC §8.
3. **With no relevant article the model is still called, asked for a clarifying reply, and the draft is flagged `low_confidence`.** Why: one code path for all drafts, and the operator sees when nothing was grounded in the KB. Changed: SPEC §8.
4. **Webhook accepts any `reply_url`; the send step refuses private, loopback and link-local addresses unless the host is in `REPLY_URL_ALLOWED_HOSTS`.** Why: the sample payload uses a placeholder domain and must never be rejected, but a body-supplied URL is an SSRF risk. Changed: SPEC §9.
5. **Rate limiter in Postgres (advisory lock and a sliding window), default 55 calls a minute.** Why: it works across any number of workers without Redis; the margin covers clock skew and provider-side accounting. Changed: SPEC §7.
6. **Keyless mode sends a real request with a placeholder credential, discards the response, and returns the static reply once a random 5-30 s has elapsed in total.** Why: it matches the task statement while keeping the call inside the same limiter and error handling. Changed: SPEC §8.

## 2026-11-06 - Tooling added with the skeleton

Basis: review of slice S0 (`feat/project-skeleton`) found these dependencies without an entry.

1. **`pytest` and `pytest-asyncio` for tests, `httpx` for both tests and outbound HTTP, `uvicorn[standard]` to serve the app.**
   Why: the code is async, so tests need an async runner. `httpx.ASGITransport` calls the application in-process without a server, and the same library is the HTTP client for the helpdesk and the provider later, so no second client is added. `uvicorn[standard]` brings the faster event loop and HTTP parser.
   Changed: `backend/pyproject.toml`, `CLAUDE.md` (stack list).

## 2026-11-06 - `src/` in the backend only

Basis: owner's question during review of slice S0.

1. **`backend/` keeps a `src/` directory; `frontend/` has none.**
   Why: the backend is Python packages that import each other, so `src/` separates importable code from `tests/`, `migrations/`, `content/` and the packaging files, as in the owner's `cadence`. The frontend is a handful of static files with no imports, tests or build step, so a `src/` there would only add a level.
   Changed: nothing; recorded so the asymmetry is explained.

## 2026-11-06 - Reviewer subagent hardening and operator-surface safety

Basis: owner asked to check the final-review agent against best practice (official subagent documentation and Anthropic's Code Review design). **Recommendation**, in effect once the owner merges it.

1. **The reviewer's shell is restricted by a hook, not only by a prompt.** The agent's `tools` line listed unrestricted `Bash`, so "read-only" depended on the prompt; a shell can also read `.env` around the settings deny rule. A `PreToolUse` hook (`.claude/hooks/reviewer_readonly.py`, tested in `backend/tests/test_reviewer_readonly_hook.py`) now allows only an explicit list of read-only commands and blocks chaining, redirects and write flags.
   Why: tool allowlists and hooks enforce, prompts only request. The hook is defense in depth, not a sandbox: `pytest` still runs repository code.
2. **The reviewer verifies each finding before reporting it, reads callers outside the diff, includes uncommitted files, judges whether tests can fail, and reports the status of earlier findings.** Anthropic's own Code Review verifies candidate bugs before posting them, which is how it keeps false reports rare.
3. **The checklist is preloaded with `skills: [invariants-check]`**, and the agent has `effort: high` and `maxTurns: 30`.
4. **Untrusted text is rendered with `textContent`, and operator POSTs require a custom header (CSRF).** The review found these two gaps in the design itself, not only in the agent: customer text reaches the operator's browser, and Basic Auth credentials are resent cross-site by browsers.
   Changed: `.claude/agents/reviewer.md`, `.claude/skills/invariants-check/SKILL.md`, SPEC §10.

## 2026-11-06 - Webhook and schema choices (slice S1)

Basis: implementation of S1 (`feat/webhook-idempotency`). **Recommendation**, in effect once the owner merges it.

1. **The repository commits before the webhook returns.** `TicketRepositoryImpl.insert_if_new` calls `commit()` itself instead of relying on `get_db`, which commits after the endpoint returns. With the installed FastAPI that post-`yield` code runs after the response has started, so without the explicit commit the helpdesk could see `200` before the row is durable. A test reads the database from a second connection at the moment `http.response.start` is sent, and it fails if the commit is removed (checked by mutation).
   Changed: `backend/src/tickets/repository.py`, `backend/tests/test_webhook.py`.
2. **An unreachable database becomes `503`.** `asyncpg` reports a refused connection or an unresolvable host as a bare `OSError`, and lost connections as `OperationalError` or `InterfaceError`. The decorator `translate_unavailable` maps these to `DatabaseUnavailableError` (`503`, code `database_unavailable`) so the helpdesk retries. Other database errors stay `500` so bugs are not hidden as outages.
   Changed: `backend/src/core/database.py`, `backend/src/core/exceptions.py`.
3. **Webhook field limits** (SPEC §4): 255 characters for ids, 320 for the email, 20 000 for the message, http or https `reply_url`. The task states none; the limits bound row size and reject junk. The email check is a plain `x@y` pattern because strict validation would need an extra dependency and a valid-looking address is all the service uses.
4. **The whole `ticket_events` table is created in S1**, including draft, attempt and lease columns that later slices fill, because SPEC §6 defines it as one table. The first Alembic revision builds it; models and migration are compared in a test, and because Alembic's comparison skips CHECK constraints a second test stores a row with every `TicketStatus` value.
5. **`/api/stats` returns every status**, zeros included, plus a total, so the UI and the simulator need no special cases for empty states.
6. **No generic CRUD base repository yet.** The `cadence` project has one; here no feature needs it, so it will be added by the first feature that does.
7. **NUL characters in text fields are rejected with `422`.** PostgreSQL text cannot hold `\x00`; accepting it would make the insert fail with a `500` and the helpdesk would retry the same poison event forever. Found by review.
8. **The engine hides statement parameters (`hide_parameters=True`).** SQLAlchemy puts the bound values into database error messages, and the unhandled-error handler logs those, which would write the full customer message and email into the logs. Found by review.
9. **A connection lost mid-statement also counts as "unavailable".** Probed against PostgreSQL: `pg_terminate_backend` during a statement raises a plain `DBAPIError` with `connection_invalidated=True` and SQLSTATE `08003`, not `OperationalError`, so the first mapping would have answered `500`. `is_unavailable` now also accepts invalidated connections, SQLSTATE classes `08` and `57`, and the pool's `TimeoutError`; other database errors still stay `500`. Pooled connections killed between requests are repaired by `pool_pre_ping`. Each outage logs one warning with the exception class only.
10. **A failed rollback cannot hide the original error.** `get_db` now suppresses errors from `rollback()` after a failure, otherwise a dead connection could replace the `503` with a `500`.
11. **Migrations take `pg_advisory_xact_lock`.** Two backend containers starting together both ran `alembic upgrade head` on an empty database and failed; with the lock the second waits and finds nothing to do. The test starts four separate processes (Alembic keeps global state, so threads are not a valid simulation) and fails without the lock.
12. **S1 covers the durable-write part of I1 and I3 only.** SPEC §12 words I1 as "fake LLM sleeping 30 s, p95 below 200 ms in the simulator run" and I3 as "kill worker and API, restart, every event reaches a draft or a terminal status". There is no LLM, worker or simulator yet, so S1 has: an import check that the code in `webhooks/` and `tickets/` does not directly import slow components or HTTP clients (it does not follow indirect imports), a 30-request latency check (p95 below 200 ms), a test that the row is committed before the response starts, a restart test that disposes and rebuilds the application, and the `503` tests. The full I1 acceptance run belongs to S7 (simulator) and the full I3 run to S4 (worker).
13. **Stored `reply_url` is the normalised URL** (`https://host` becomes `https://host/`, internationalised hosts become punycode) because it passes through pydantic's URL type. This is harmless unless a later slice compares it byte for byte with what the helpdesk sent.

## 2026-11-06 - Knowledge base and search (slice S2)

Basis: implementation of S2 (`feat/knowledge-base-search`). **Recommendation**, in effect once the owner merges it.

1. **Articles are Markdown files in `backend/content/kb/`, synced into PostgreSQL when the container starts.** Each file has front matter (`slug`, `title`); the file name must equal the slug. The loader validates every file before it touches the database (an empty directory is refused so a wrong path cannot wipe the table), then upserts all rows in one statement ordered by slug and deletes rows whose file is gone, so containers starting together cannot deadlock. The front matter is parsed by hand to avoid a YAML dependency.
2. **Eight articles about a fictional product, Vistara, written by Claude** (the task asks for AI-generated articles), 114-133 words each. After measuring, two natural synonyms customers use were added ("акаунт" and "ексель"); retrieval quality on a small corpus depends on the vocabulary of the articles.
3. **Search runs in PostgreSQL with `pg_trgm` per word, not full-text search alone.** PostgreSQL has no Ukrainian text-search configuration, and trigram similarity tolerates word endings (`експортувати` ~ `експорт`). The score is 0.8 x mean best word similarity + 0.2 x scaled `ts_rank('simple')`, with a threshold of 0.4 and a limit of 3. The whole knowledge base is scored on every query, which is fine for the 5-10 articles the task describes and would need an index or a limit if it grew.
4. **Measured quality on 16 sample tickets and 12 unrelated queries** (the same queries the weights and threshold were tuned on, so it is an optimistic figure): the right article is first for 14 of 16 and within the first three for 16 of 16; all 12 unrelated queries (two contain no usable words) return nothing. The lowest score of a right first result is 0.449 and the highest score of an unrelated query is 0.354, so the 0.4 threshold sits in the gap. Two queries rank the right article second ("ексель" spelled in Cyrillic, "заблокувало ... спроб входу"). Because the drafting step receives three articles, recall within the first three is the number that matters. Two alternatives were tried on the same queries and rejected: word coverage and inverse document frequency weighting fixed neither miss, and the second narrowed the gap between right and unrelated results.
5. **English text matches only on Latin tokens** (PDF, API, CSV, Excel), because the articles are Ukrainian and there is no translation step.
6. **`GET /api/kb/{slug}` is public and returns the raw text.** Customers receive links to articles, and the pages must insert the text with `textContent` (SPEC §10). Unknown or malformed slugs answer `404`.
7. **New settings:** `KB_CONTENT_DIR` (default `content/kb`) and `KB_MIN_SCORE` (default 0.4).

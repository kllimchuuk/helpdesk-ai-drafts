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

Basis: implementation of S2 (`feat/knowledge-base-search`) and its review. **Recommendation**, in effect once the owner merges it.

1. **Articles are Markdown files in `backend/content/knowledge_base/`, synced into PostgreSQL when the container starts.** Each file has front matter (`slug` up to 100 characters, `title` up to 255), and the file name must equal the slug. The loader validates every file before it touches the database; an empty or missing directory is refused so a wrong path cannot wipe the table. It then upserts all rows in one statement ordered by slug (containers starting together take row locks in the same order) and deletes rows whose file is gone. The front matter is parsed by hand to avoid a YAML dependency.
2. **Eight articles about a fictional product, Vistara, written by Claude** (the task asks for AI-generated articles), 114-133 words each. After measuring, two natural synonyms customers use were added ("акаунт", "ексель"): retrieval on a small corpus depends on the vocabulary of the articles.
3. **Search runs in PostgreSQL with `pg_trgm` per word.** PostgreSQL has no Ukrainian text-search configuration, and trigram similarity tolerates word endings (`експортувати` ~ `експорт`). The article score is 0.8 x the mean best word similarity + 0.2 x scaled `ts_rank('simple')`. An article is accepted when the score reaches 0.4 or when at least 3 words match it with similarity 0.7 or more; the top 3 are returned and up to 100 distinct words are used. The whole table is scored on every query, which is fine for the 5-10 articles the task describes. The GIN index on `tsv` is not used by that query today; it is kept for a larger knowledge base.
4. **The second acceptance rule was added after review.** The first version used the mean score and a threshold only. A long, polite ticket with the problem at the end ("Добрий день! Пишу вам вже втретє ... Не можу експортувати звіт у PDF") scored below the threshold and found nothing, because the filler words pull the mean down. Measured on five long relevant and four long unrelated tickets, no threshold on the mean can separate them (the lowest relevant long score is 0.278, the highest unrelated long score is 0.354), while the number of strongly matching words does: at least 4 for relevant tickets and at most 2 for unrelated ones. Averaging only the best K words, word-coverage fractions and inverse document frequency weights were tried and did not remove the overlap; the IDF weights also narrowed the gap on short tickets.
5. **Measured quality**, measured once through the real service with an ad-hoc script that is not committed, on 21 relevant tickets (8 short, 8 harder, 5 long) and 16 unrelated ones (2 of them have no usable words): the right article is first for 19 of 21 and among the accepted top three for 21 of 21, and none of the 16 unrelated tickets is accepted. The two first-place misses rank the right article second ("ексель" spelled in Cyrillic; "заблокувало ... спроб входу"). The tests pin first place for 13 tickets, the first three for the other 8, and that nothing unrelated is accepted; the "19 of 21" total and the score and strong-word bounds quoted in item 4 are not asserted anywhere. These queries were written by the same author as the articles and the weights and thresholds were tuned on them, so the figures are optimistic. The drafting step receives three articles, so the top-three figure is the one that matters.
6. **`GET /api/kb/{slug}` is public and returns the raw text.** Customers receive links to articles, and the pages must insert the text with `textContent` (SPEC §10). A slug that is not lowercase words joined by hyphens, or is longer than 100 characters, answers `404` without a database query; `/api/kb/%00` used to answer `500` because PostgreSQL text cannot hold a NUL character.
7. **Limits of the search:** English text matches only on Latin tokens (PDF, API, CSV, Excel) because the articles are Ukrainian; a ticket with more than 100 distinct usable words is cut after the first 100. The second acceptance rule has a margin of one word on each side (threshold 3, unrelated maximum 2, relevant minimum 4 in the sample) and counts each inflection of a word separately (`рахунок`, `рахунку` and `рахунки` are three words), so a long unrelated ticket that happens to mention three generic words such as team, administrator and mail could be accepted. The consequence is bounded because the model is told to answer only from the supplied articles; counting one word per stem would be the next step once real tickets exist (the simulator in S7).
8. **A knowledge base that cannot be loaded does not stop the service.** `entrypoint.sh` logs a warning and starts with the articles already stored if `knowledge_base.loader` fails. Webhook intake (invariant I3) must not go down because of article content, and the articles ship inside the image and are checked by a test in CI. The cost is that a broken article shows up only in the logs; with an empty table the search finds nothing and drafts will be flagged as low confidence.
9. **SPEC edits made in this slice:** the S2 "done when" now names the measured criterion instead of "five sample tickets", and §8 describes the real retrieval; new settings `KB_CONTENT_DIR` (default `content/knowledge_base`) and `KB_MIN_SCORE` (default 0.4) are listed in §14 and `.env.example`.

## 2026-11-07 - LLM client, rate limiter, daily cap and keyless mode (slice S3)

Basis: the S3 plan agreed with the owner before coding (plan mode). **Recommendation**, in effect once the owner merges the slice.

1. **New dependency: the official `anthropic` SDK** (SPEC §3 already fixes it). It is used only inside `backend/src/llm/`. Version 2.6.0 was installed. It is built on `httpx2`, so tests build its client on a `httpx2` mock transport and never touch the network. Two facts checked in the installed package: `output_config` takes `effort` and `format` (`json_schema`), and the key is sent as `Authorization: Bearer`. No real call was made (there is no key), so the structured-output request is verified against the SDK's types and a mock, not against the live API; the first run with a real key is the first real check.
2. **One atomic reservation decides everything.** `LlmCallService.reserve` runs in a single short transaction under `pg_advisory_xact_lock` (a key different from the migration lock): it counts the calls of the last 60 s, returns how long to wait when the limit is reached, and otherwise picks the route and inserts the `llm_calls` row. The repository only offers the steps (lock, count, wait, record, commit); the decisions live in the service. Window check, route choice and insert cannot interleave across workers, so I4 and I9 hold for any number of processes. Rejected: a counter in memory (breaks with two workers), Redis (a second moving part for 60 calls a minute), SDK-side rate limiting (does not know the other workers).
3. **Waiting and calling happen outside any transaction** (CLAUDE.md rule). The limiter reserves, commits, sleeps when told to wait, and tries again; the provider call follows the commit.
4. **The SDK's own retries are off (`max_retries=0`).** A hidden retry would be a provider call the limiter never counted and would break I4. Every attempt goes back through the limiter; retry and backoff policy belongs to the generation worker (S4), which classifies the typed errors.
5. **The daily cap counts provider calls only.** Keyless requests also reach the provider URL and take a limiter slot (I4), but they are free, so they do not use up `LLM_DAILY_CALL_CAP`. The day is the UTC day by the database clock. After the cap the service takes the keyless path until midnight UTC (I9). Default cap 500 a day, about $0.35 at the SPEC estimate of $0.0007 a draft; this is an estimate and the owner can change it.
6. **A worker that crashes between the reservation and the call wastes one slot.** That errs on the safe side of I4 and is accepted.
7. **Errors are typed `AppException` subclasses** so S4 never parses strings: rate limited (with `Retry-After`), transient (5xx, timeout, connection), rejected (other 4xx), refusal, invalid output.
8. **The keyless request uses the same SDK client with a placeholder credential**, discards the response (an authentication error is expected) and waits until a random 5-30 s has elapsed since the start. The static reply is short, in Ukrainian because the sample tickets are Ukrainian, and the result carries `is_static=True` so the UI can say so.
9. **Settings added** (SPEC §14, `.env.example`): `LLM_REQUEST_TIMEOUT_S` (default 45) next to the variables SPEC already lists. `ANTHROPIC_API_KEY` is a `SecretStr` and is never logged.
10. **The configured limit cannot exceed 60.** `LLM_RATE_LIMIT_PER_MINUTE` is validated to 1-60, so a typo cannot break I4; the delay bounds must be ordered. `LLM_DAILY_CALL_CAP` accepts 0, which sends everything down the keyless path.
11. **Compose passes `ANTHROPIC_API_KEY` and `LLM_DAILY_CALL_CAP` to the backend, both optional.** Nothing in S3 calls the model at runtime yet (the worker is S4), so this only prepares the wiring.

Review findings (reviewer pass 1, "Fix before merge"), all fixed in the commits after the first three:

12. **The keyless request discards every outcome, not only typed errors.** A `200` with a broken body (`{}`, HTML from a proxy) used to escape as an untyped `AttributeError` and fail the ticket instead of producing the static reply. The probe now swallows any `Exception` (cancellation still passes) and is cut off by `asyncio.timeout` at the drawn delay, so a hanging connection cannot stretch the reply to the 45 s request timeout. The keyed client also turns a broken `200` (no content, a non-message body) into `LLMInvalidOutputError` instead of a bare `TypeError`.
13. **The keyless delay starts when the client is called, after the limiter has granted the slot.** Time spent waiting for a slot comes on top, so under load the visible delay can exceed 30 s. This follows SPEC §8 ("since the start" of the request) and is accepted.
14. **`Retry-After` is kept only when it is a finite non-negative number and is capped at one hour.** `inf`, `nan`, negative values and HTTP dates become `None`, and a huge finite value such as `1e300` is cut to 3600 s, so the worker never sleeps without bound and the payload stays valid JSON. The cap lives in `llm/anthropic_client.py` (`MAX_RETRY_AFTER_S`); S4 still decides how long it really waits.
15. **Typed errors carry no exception chain at all.** The provider response body and the model reply may hold customer text, and `from None` would only hide the chain in tracebacks (`__context__` stays set). The errors are built inside the `except` blocks and raised after them, so both `__cause__` and `__context__` are `None`; tests assert exactly that. The payload keeps only the status code, the exception class name or a fixed reason. A malformed content block (missing or non-string `text`, a non-object item) becomes `LLMInvalidOutputError` as well.
16. **The time conditions use a subquery so the `called_at` index is used.** `clock_timestamp()` is volatile; compared directly, PostgreSQL scanned the whole table under the global lock. Measured once with `EXPLAIN ANALYZE` on a temporary table of 200 000 rows: 8.8 ms sequential scan against 0.02 ms with the index. A test pins `Index Cond` in the plan for both conditions. Nothing prunes `llm_calls` yet (up to about 80 000 rows a day at the limit); pruning old rows is left for later.
17. **Known limits, not changed:** a reservation is stamped when it is inserted and the provider call follows the commit, so a stalled event loop can shift a send after its window; the default of 55 against the limit of 60 leaves the margin. Each reservation waiting on the advisory lock holds a pooled connection, which S4 must size against its 20 generation tasks. The UTC-day expression is correct by reading, but the test engine forces a UTC session time zone, so a regression to a session-time-zone version would not be caught by the tests.
18. **`KEYLESS_DELAY_MIN_S` must be at least 1.** The probe is cut off when the drawn delay ends, so a delay near zero would cancel it before it connects and the "real request" would never leave the process although a slot was recorded. The default is 5.

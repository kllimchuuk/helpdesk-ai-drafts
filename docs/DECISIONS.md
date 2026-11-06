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

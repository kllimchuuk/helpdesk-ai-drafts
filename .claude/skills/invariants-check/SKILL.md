---
name: invariants-check
description: Checklist of the service invariants (SPEC §5) with concrete things to look for in code and tests. Use when reviewing a diff, before committing changes to the webhook, queue, workers, rate limiter, LLM client or delivery code, or when asked whether a change is safe.
---

# Invariant checklist

For each item answer pass, fail or not touched, and point at the code or test that proves it. The source is `docs/SPEC.md` §5; tests are listed in §12.

| ID | Look for | Red flag |
|---|---|---|
| I1 | The webhook route only validates, inserts and returns. | An import or call to `llm`, `drafting`, `knowledge_base` or `delivery` in `webhooks/`; an `await` on a network call before the response. |
| I2 | `INSERT ... ON CONFLICT DO NOTHING` on a `UNIQUE(event_id)` column; duplicate returns 200 `duplicate`. | A `SELECT` for the event before the insert; catching `IntegrityError` after a separate existence check. |
| I3 | The event row is committed before the 200; database errors map to 503. | Acknowledging before commit; an in-memory queue or background task holding the only copy. |
| I4 | Every provider request, including the keyless one and retries, goes through the limiter (advisory lock + sliding window in `llm_calls`). | A direct SDK or `httpx` call that skips the limiter; a limiter held per process only. |
| I5 | Claims use `FOR UPDATE SKIP LOCKED` and set `locked_until`; a heartbeat extends it; expired rows are reclaimable. | A claim without a lease; a lease shorter than a worst-case call plus limiter wait. |
| I6 | Outcome classification: definite failure retried, ambiguous (`ReadTimeout`, dropped connection, expired `sending` lease) goes to `send_unknown`; `Idempotency-Key` sent. | An automatic retry of a timeout when `SEND_RETRY_AMBIGUOUS` is false; an expired `sending` row put back to `approved`. |
| I7 | Status changes are `UPDATE ... WHERE status = :expected RETURNING`; zero rows means the transition lost. | Read-modify-write in Python; a status set without the expected-state condition. |
| I8 | Keyless path sends a real request with a placeholder credential, ignores the response, and returns the static reply once a random 5-30 s has elapsed in total. | Treating the 401 as an error; skipping the request; a different downstream code path for static replies. |
| I9 | The daily counter is checked before the provider call and flips to the keyless path at the cap. | A cap that only logs; a cap counted per process. |

Structure and safety checks that apply to every diff:

- SQL outside a repository, or a router containing logic.
- A database transaction held open across a provider or helpdesk call.
- `reply_url` used without the host check (private, loopback and link-local addresses refused unless allow-listed); redirects followed.
- Secrets, API keys, provider response bodies or full customer messages in log lines or error responses.
- Untrusted text (customer message, draft, KB article, error text) put into the page with `innerHTML` or `insertAdjacentHTML`; it must go in with `textContent` or be escaped, and any rendered KB markdown must be sanitized.
- An operator route (`/api/tickets*`) without the Basic Auth dependency, or a public route that is not listed in SPEC §4.
- A state-changing operator route that accepts a request without the custom header required by SPEC §10: browsers resend cached Basic credentials on cross-site form posts, so without it any web page could approve a reply.
- A new dependency without a `docs/DECISIONS.md` entry.
- Behavior change without a test, or a test that cannot fail. For every new test name the bug that would make it fail; a test that passes on a stub or on an empty implementation proves nothing.
- A concurrency test that passes once but was not run repeatedly; it may be flaky or may not exercise the race at all.
- A docs file that no longer matches the code (SPEC, DECISIONS, README, `.env.example`).

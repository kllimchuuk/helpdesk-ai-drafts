---
name: spec-slice
description: Work loop for implementing one slice (S0-S9) of the Helpdesk AI Drafts spec. Use when starting or continuing a slice, adding a feature package, or when the user says "next slice" or names one. Covers reading the spec, branching, test first, implementation rules, checks and the local commit.
---

# Implementing a slice

Follow these steps in order. The slice list is in `docs/SPEC.md` §13; the rules behind it are in `CLAUDE.md`.

1. **Read.** Open the slice in SPEC §13 and every section it names (§4 contracts, §5 invariants, §6 data model, §7-§9 behavior, §10-§11 UI and tools). Read the acceptance tests for its invariants in §12. If the SPEC is silent or wrong, stop and report "Decision needed" with a recommendation; do not guess.
2. **Branch.** Check `git branch --show-current`. Work on a branch named by commit type for this slice (`feat/webhook-idempotency`). Never on `main`.
3. **Test first.** Write the failing test for the acceptance criterion, in `backend/tests/test_<module>.py`, against real Postgres with fakes from `tests/fakes.py`. Run it and see it fail for the right reason.
4. **Implement.** Smallest code that passes, following SPEC §13 rules:
   - feature package with `models`, `repository` (ABC + Impl), `service`, `schemas`, `exceptions`, and `router` only if it exposes HTTP;
   - all SQL in repositories; routers hold no logic;
   - no database transaction open while calling the provider or the helpdesk;
   - Alembic migration for schema changes (one per slice);
   - comments only for a non-obvious reason.
5. **Check.** From `backend/`: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`. Everything green before committing. For concurrency code also run the relevant test several times to expose flakiness.
6. **Document.** If the change deviates from the SPEC or settles a choice, add the entry to `docs/DECISIONS.md` and edit the SPEC in the same commit.
7. **Commit locally.** Stage by explicit path. One logical change per commit, module and its tests together. Subject in English describing the behavior, then the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push, never amend or reset history.
8. **Hand over.** Show `git log --stat main..HEAD`, then report in the `report` skill's shape. Suggest running the `reviewer` subagent before the owner opens the pull request.

If a step fails twice for the same reason, stop and say what you tried instead of looping.

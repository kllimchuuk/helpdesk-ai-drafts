---
name: report
description: Writes the stage report for this project in the fixed shape (Done / Numbers / Deviations from SPEC / Decision needed / Next). Use at the end of a slice, for a pull request description, for docs/REPORT.md, or when the user asks "report", "what did you do" or "summarize the branch".
---

# Report

Use exactly this shape. It is used as the pull request description and, aggregated, as `docs/REPORT.md`.

```
REPORT <date> - <slice or branch>
Done: what now works, in behavior terms; commits as `git log --oneline main..HEAD`.
Numbers: measured values only, each with the command or file it came from; "none" if nothing was measured.
Deviations from SPEC: each deviation and why, with the DECISIONS entry; "none" if there are none.
Decision needed: open questions, each with your recommendation; "none" if there are none.
Next: the next slice or step.
```

Rules:

- **Measured only.** Never write a latency, throughput, cost or test count you did not obtain by running something in this session. Give the command (`docker compose run --rm simulator ...`, `uv run pytest -q`) next to the figure. If you could not run it, write "not measured".
- **Say what failed.** Failing tests, skipped checks and unverified assumptions go in the report, not out of it.
- **Review result.** If the `reviewer` subagent ran, include its verdict and the findings you fixed, with the `fix:` commits.
- **AI-workflow notes.** When the agent's first attempt was wrong and a test, a review or the owner caught it, record it in one line (what was wrong, how it was caught, what changed). The final `docs/REPORT.md` collects these under "How I worked with AI".
- Keep it short: a report is read, not browsed. English, no marketing words.

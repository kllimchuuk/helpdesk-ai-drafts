#!/usr/bin/env python3
"""PreToolUse hook for the reviewer subagent: let only read-only Bash through.

Claude Code passes the tool call as JSON on stdin. Exit code 2 blocks the call and
shows stderr to the agent. The check is an allowlist, so anything not recognised is
blocked. It is defense in depth on top of the agent's tool list, not a sandbox.
"""

import json
import re
import shlex
import sys

BLOCK = "Blocked by the reviewer read-only hook"

SHELL_SYNTAX = re.compile(r"[;&<>`\\$\n\r]")

GIT_READ_ONLY = "status|diff|log|show|ls-files|rev-parse|merge-base|blame|grep|ls-tree"
UV = r"uv run (?:--directory [\w./-]+ )?"

COMMANDS = (
    re.compile(rf"git (?:{GIT_READ_ONLY})(?: .*)?"),
    re.compile(r"git branch(?: (?:--show-current|-a|-r|-vv|--list))?"),
    re.compile(rf"{UV}ruff check(?: .*)?"),
    re.compile(rf"{UV}ruff format (?:.* )?(?:--check|--diff)(?: .*)?"),
    re.compile(rf"{UV}pytest(?: .*)?"),
    re.compile(r"docker compose (?:config|ps)(?: .*)?"),
)

FILTERS = re.compile(
    r"(?:head|tail)(?: -n ?\d+| -\d+)?|wc(?: -[lwc])?|sort|uniq(?: -c)?"
)

DENIED_LONG_ARGUMENTS = (
    "--output",
    "--ext-diff",
    "--textconv",
    "--no-index",
    "--untracked",
    "--open-files-in-pager",
    "--fix",
    "--add-noqa",
    "--unsafe-fixes",
    "--junit",
    "--basetemp",
    "--html",
    "--cov",
    "--confcutdir",
)
DENIED_SHORT_ARGUMENTS = ("-O", "-o")


def deny(reason: str) -> None:
    print(
        f"{BLOCK}: {reason}. The reviewer may only run read-only git commands, "
        "ruff check, ruff format --check, pytest and docker compose config or ps, "
        "optionally piped into head, tail, wc, sort or uniq.",
        file=sys.stderr,
    )
    sys.exit(2)


def check(command: str) -> None:
    command = command.strip()
    if not command:
        deny("empty command")
    if SHELL_SYNTAX.search(command):
        deny("shell syntax that can chain or redirect")

    first, *filters = (segment.strip() for segment in command.split("|"))

    if not any(pattern.fullmatch(first) for pattern in COMMANDS):
        deny(f"command not on the allowlist: {first!r}")
    for segment in filters:
        if not FILTERS.fullmatch(segment):
            deny(f"pipe target not on the allowlist: {segment!r}")

    try:
        arguments = shlex.split(first)
    except ValueError:
        deny("unbalanced quotes")
    for argument in arguments:
        if (
            argument.startswith(DENIED_LONG_ARGUMENTS)
            or argument in DENIED_SHORT_ARGUMENTS
        ):
            deny(f"argument not allowed: {argument!r}")


def main() -> None:
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Bash":
        return
    check(event.get("tool_input", {}).get("command", ""))


if __name__ == "__main__":
    main()

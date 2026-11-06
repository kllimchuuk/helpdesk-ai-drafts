import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "reviewer_readonly.py"
)
BLOCK_MESSAGE = "Blocked by the reviewer read-only hook"


def run_hook(command: str, tool_name: str = "Bash") -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git diff main...HEAD",
        "git diff main...HEAD --stat",
        "git log --format='%h %s' main..HEAD",
        "git show cdffbdd:CLAUDE.md",
        "git ls-files",
        "git branch --show-current",
        "git grep -n SKIP_LOCKED",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run pytest -q",
        "uv run pytest tests/test_health.py -q",
        "docker compose config --quiet",
        "git log --oneline main..HEAD | head -20",
        "git diff main...HEAD | wc -l",
        "git log -p main..HEAD",
    ],
)
def test_read_only_commands_are_allowed(command: str) -> None:
    result = run_hook(command)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "touch notes.txt",
        "rm -rf backend",
        "echo hi > file.txt",
        "echo hi >> file.txt",
        "git commit -m x",
        "git add .",
        "git push origin main",
        "git reset --hard",
        "git checkout main",
        "git switch main",
        "git branch -D feat/project-skeleton",
        "git diff --output=out.patch",
        "git -c core.pager=sh log",
        "git status; rm -rf .",
        "git status && rm -rf .",
        "git status `touch x`",
        "git status $(touch x)",
        "git log | sh",
        "git log | tee out.txt",
        "cat .env",
        "uv run ruff check . --fix",
        "uv run ruff format .",
        "uv run pytest --junitxml=out.xml",
        'uv run python -c \'open("x","w")\'',
        "uv run ruff check . --output-file out.txt",
        "docker compose config -o out.yml",
        "git grep -e foo --no-index",
        "docker compose up -d",
        "docker compose down",
        "curl https://example.com",
        "sed -i s/a/b/ backend/src/main.py",
        "git status\nrm -rf .",
    ],
)
def test_anything_that_can_change_state_is_blocked(command: str) -> None:
    result = run_hook(command)

    assert result.returncode == 2
    assert BLOCK_MESSAGE in result.stderr


def test_other_tools_are_not_touched() -> None:
    result = run_hook("anything", tool_name="Read")

    assert result.returncode == 0


def test_missing_command_is_blocked() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {}}),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert BLOCK_MESSAGE in result.stderr

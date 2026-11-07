import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
LOGIC = (
    ast.If,
    ast.IfExp,
    ast.Match,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.BoolOp,
)
REPOSITORIES = sorted(SRC.glob("*/repository.py"))


def test_every_feature_repository_is_checked() -> None:
    assert {path.parent.name for path in REPOSITORIES} >= {
        "tickets",
        "llm",
        "knowledge_base",
    }


@pytest.mark.parametrize("path", REPOSITORIES, ids=lambda path: path.parent.name)
def test_a_repository_runs_queries_and_holds_no_logic(path: Path) -> None:
    """Branches, loops and defaults belong in the service that calls the repository."""
    tree = ast.parse(path.read_text())

    found = [
        f"line {node.lineno}: {type(node).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, LOGIC)
    ]

    assert found == []

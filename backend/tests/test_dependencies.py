import ast
import sys
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"


def declared_distributions() -> set[str]:
    dependencies = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    names = set()
    for requirement in dependencies:
        name = requirement.split("[")[0]
        for separator in ">=<!~ ":
            name = name.split(separator)[0]
        names.add(name.lower().replace("-", "_"))
    return names


def imported_top_level_modules() -> dict[str, Path]:
    first_party = {path.name for path in SRC.iterdir()} | {
        path.stem for path in SRC.glob("*.py")
    }
    found: dict[str, Path] = {}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top not in sys.stdlib_module_names and top not in first_party:
                    found.setdefault(top, path)
    return found


def test_every_third_party_import_in_src_is_declared() -> None:
    """A package that only another one pulls in can vanish on that one's upgrade."""
    declared = declared_distributions()

    undeclared = {
        module: str(path.relative_to(BACKEND))
        for module, path in imported_top_level_modules().items()
        if module.lower().replace("-", "_") not in declared
    }

    assert undeclared == {}

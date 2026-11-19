import re
from pathlib import Path

import pytest
import yaml

PROD_FILE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


def services() -> dict[str, dict]:
    return yaml.safe_load(PROD_FILE.read_text())["services"]


def test_prod_runs_in_production_mode() -> None:
    assert services()["backend"]["environment"]["APP_ENV"] == "production"


@pytest.mark.parametrize(
    ("service", "name"),
    [
        ("backend", "OPERATOR_USER"),
        ("backend", "OPERATOR_PASSWORD"),
        ("backend", "DATABASE_URL"),
        ("worker", "DATABASE_URL"),
        ("worker", "PUBLIC_BASE_URL"),
        ("db", "POSTGRES_PASSWORD"),
    ],
)
def test_prod_requires_a_secret_instead_of_defaulting(service: str, name: str) -> None:
    """`${NAME:?}` stops `compose up` when the value is missing; no `:-` fallback."""
    value = str(services()[service]["environment"][name])

    assert ":?" in value
    assert ":-" not in value


def test_prod_publishes_only_the_frontend() -> None:
    published = {
        name: service["ports"]
        for name, service in services().items()
        if "ports" in service
    }

    assert published == {"frontend": ["80:80"]}


def test_prod_does_not_trust_any_reply_host_by_default() -> None:
    value = str(services()["worker"]["environment"]["REPLY_URL_ALLOWED_HOSTS"])

    assert value == "${REPLY_URL_ALLOWED_HOSTS:-}"


def test_prod_keeps_the_mock_helpdesk_out_of_the_default_stack() -> None:
    assert services()["mock-helpdesk"]["profiles"] == ["demo"]


def test_prod_restarts_every_long_running_service() -> None:
    for name in ("db", "backend", "worker", "frontend"):
        assert services()[name]["restart"] == "unless-stopped"


def test_env_example_lists_exactly_the_variables_production_requires() -> None:
    example = PROD_FILE.parent / ".env.example"
    listed = {
        line.split("=")[0] for line in example.read_text().splitlines() if "=" in line
    }
    required = set(re.findall(r"\$\{(\w+):\?", PROD_FILE.read_text()))

    assert listed == required

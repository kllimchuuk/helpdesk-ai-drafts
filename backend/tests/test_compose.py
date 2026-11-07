import re
from pathlib import Path

import pytest
import yaml

from config import Settings

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
INTERPOLATION = re.compile(r"\$\{(?P<name>\w+):-(?P<default>[^}]*)\}")
WORKER_PREFIXES = ("LLM_", "KEYLESS_", "SEND_", "REPLY_URL_")
COMPOSE_DEFAULTS = {"REPLY_URL_ALLOWED_HOSTS": "mock-helpdesk"}
WORKER_EXTRAS = ("ANTHROPIC_API_KEY", "KB_MIN_SCORE", "PUBLIC_BASE_URL")


def worker_settings() -> list[str]:
    return sorted(
        name
        for name in Settings.model_fields
        if name.startswith(WORKER_PREFIXES) or name in WORKER_EXTRAS
    )


def worker_environment() -> dict[str, str]:
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    return compose["services"]["worker"]["environment"]


def default_text(name: str) -> str:
    if name in COMPOSE_DEFAULTS:
        return COMPOSE_DEFAULTS[name]
    value = Settings.model_fields[name].default
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


@pytest.mark.parametrize("name", worker_settings())
def test_compose_forwards_every_worker_setting_from_the_root_env(name: str) -> None:
    """`.env` is not in the image, so a setting compose does not forward is ignored."""
    match = INTERPOLATION.fullmatch(str(worker_environment().get(name, "")))

    assert match is not None, f"{name} is not forwarded to the worker"
    assert match["name"] == name
    assert match["default"] == default_text(name), "the defaults have drifted"

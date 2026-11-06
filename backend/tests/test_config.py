import pytest

from config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_settings_load_without_any_environment() -> None:
    settings = Settings(_env_file=None)

    assert settings.APP_ENV == "local"
    assert settings.APP_PORT == 8000
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")


def test_environment_overrides_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "9100")

    assert Settings(_env_file=None).APP_PORT == 9100


def test_unknown_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOMETHING_ELSE", "x")

    Settings(_env_file=None)

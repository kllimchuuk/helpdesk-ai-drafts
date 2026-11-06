import pytest

from config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_settings_load_without_any_environment() -> None:
    settings = Settings(_env_file=None)

    assert settings.APP_ENV == "local"
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")


def test_environment_overrides_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    assert Settings(_env_file=None).APP_ENV == "production"


def test_unknown_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOMETHING_ELSE", "x")

    Settings(_env_file=None)


def test_the_llm_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.ANTHROPIC_API_KEY.get_secret_value() == ""
    assert settings.LLM_MODEL == "claude-haiku-5-5"
    assert settings.LLM_RATE_LIMIT_PER_MINUTE == 55
    assert settings.LLM_DAILY_CALL_CAP == 500
    assert (settings.KEYLESS_DELAY_MIN_S, settings.KEYLESS_DELAY_MAX_S) == (5, 30)


@pytest.mark.parametrize(
    "overrides",
    [
        {"LLM_RATE_LIMIT_PER_MINUTE": 0},
        {"LLM_RATE_LIMIT_PER_MINUTE": 61},
        {"LLM_DAILY_CALL_CAP": -1},
        {"KEYLESS_DELAY_MIN_S": 31},
        {"KEYLESS_DELAY_MIN_S": -1},
        {"LLM_REQUEST_TIMEOUT_S": 0},
    ],
)
def test_unsafe_llm_settings_are_rejected(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **overrides)

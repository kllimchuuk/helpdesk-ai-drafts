from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OPERATOR_USER = "operator"
DEFAULT_OPERATOR_PASSWORD = "operator"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "local"
    KB_CONTENT_DIR: str = "content/knowledge_base"
    KB_MIN_SCORE: float = 0.4
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = "claude-haiku-5-5"
    LLM_RATE_LIMIT_PER_MINUTE: int = Field(default=55, ge=1, le=60)
    LLM_DAILY_CALL_CAP: int = Field(default=500, ge=0)
    LLM_REQUEST_TIMEOUT_S: float = Field(default=45.0, gt=0)
    KEYLESS_DELAY_MIN_S: float = Field(default=5.0, ge=1)
    KEYLESS_DELAY_MAX_S: float = Field(default=30.0, ge=0)
    LLM_CONCURRENCY: int = Field(default=20, ge=1, le=100)
    PUBLIC_BASE_URL: str = "http://localhost:8080"
    OPERATOR_USER: str = DEFAULT_OPERATOR_USER
    OPERATOR_PASSWORD: SecretStr = SecretStr(DEFAULT_OPERATOR_PASSWORD)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/helpdesk"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5434/helpdesk_test"
    )

    @model_validator(mode="after")
    def keyless_delay_bounds_are_ordered(self) -> "Settings":
        if self.KEYLESS_DELAY_MIN_S > self.KEYLESS_DELAY_MAX_S:
            raise ValueError("KEYLESS_DELAY_MIN_S must not exceed KEYLESS_DELAY_MAX_S")
        return self

    @model_validator(mode="after")
    def production_has_its_own_operator_credentials(self) -> "Settings":
        if self.APP_ENV == "production" and (
            self.OPERATOR_USER == DEFAULT_OPERATOR_USER
            or self.OPERATOR_PASSWORD.get_secret_value() == DEFAULT_OPERATOR_PASSWORD
        ):
            raise ValueError(
                "Set OPERATOR_USER and OPERATOR_PASSWORD: the defaults are refused "
                "when APP_ENV=production"
            )
        return self


settings = Settings()

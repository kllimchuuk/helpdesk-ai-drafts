from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/helpdesk"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5434/helpdesk_test"
    )

    @model_validator(mode="after")
    def keyless_delay_bounds_are_ordered(self) -> "Settings":
        if self.KEYLESS_DELAY_MIN_S > self.KEYLESS_DELAY_MAX_S:
            raise ValueError("KEYLESS_DELAY_MIN_S must not exceed KEYLESS_DELAY_MAX_S")
        return self


settings = Settings()

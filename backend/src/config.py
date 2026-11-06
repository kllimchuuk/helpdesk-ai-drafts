from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "local"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/helpdesk"
    TEST_DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5434/helpdesk_test"
    )


settings = Settings()

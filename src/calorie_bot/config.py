"""Application configuration. No other module reads os.environ directly."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ------------------------------------------------------------
    telegram_bot_token: SecretStr = Field(..., alias="TELEGRAM_BOT_TOKEN")

    # --- Model providers -----------------------------------------------------
    google_api_key: SecretStr = Field(..., alias="GOOGLE_API_KEY")
    apify_api_token: SecretStr | None = Field(None, alias="APIFY_API_TOKEN")
    # OpenRouter API key (optional) — when set the app will prefer OpenRouter
    openrouter_api_key: SecretStr | None = Field(None, alias="OPENROUTER_API_KEY")
    # Use the provider-prefixed model name supported by the selected provider.
    model_name: str = Field("google:gemini-3.5-flash", alias="MODEL_NAME")
    max_output_tokens: int = Field(4096, alias="MAX_OUTPUT_TOKENS")

    # --- Database ------------------------------------------------------------
    # Prefer the full connection URI in `DATABASE_URL`. Alternatively you can
    # provide the individual connection pieces (host/port/database/user/password)
    # which are used to build the pool when `DATABASE_URL` is not set.
    # Use the *session* pooler (port 5432) for long-lived asyncpg pools, or the
    # transaction pooler (6543) together with DB_STATEMENT_CACHE_SIZE=0.
    database_url: SecretStr | None = Field(None, alias="DATABASE_URL")
    db_host: str | None = Field(None, alias="DB_HOST")
    db_port: int | None = Field(None, alias="DB_PORT")
    db_name: str | None = Field(None, alias="DB_NAME")
    db_user: str | None = Field(None, alias="DB_USER")
    db_password: SecretStr | None = Field(None, alias="DB_PASSWORD")
    db_min_pool_size: int = Field(1, alias="DB_MIN_POOL_SIZE")
    db_max_pool_size: int = Field(10, alias="DB_MAX_POOL_SIZE")
    db_statement_cache_size: int = Field(0, alias="DB_STATEMENT_CACHE_SIZE")
    db_command_timeout: float = Field(30.0, alias="DB_COMMAND_TIMEOUT")
    run_schema_init_on_startup: bool = Field(True, alias="RUN_SCHEMA_INIT_ON_STARTUP")

    # --- Behaviour -----------------------------------------------------------
    # Application environment: 'development' enables local defaults for DB.
    app_env: str = Field("production", alias="APP_ENV")

    default_timezone: str = Field("UTC", alias="DEFAULT_TIMEZONE")
    max_photo_bytes: int = Field(8 * 1024 * 1024, alias="MAX_PHOTO_BYTES")
    max_video_bytes: int = Field(50 * 1024 * 1024, alias="MAX_VIDEO_BYTES")
    history_turns_kept: int = Field(12, alias="HISTORY_TURNS_KEPT")
    history_ttl_seconds: int = Field(30 * 60, alias="HISTORY_TTL_SECONDS")
    agent_timeout_seconds: float = Field(90.0, alias="AGENT_TIMEOUT_SECONDS")
    log_level: str = Field("INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton so importing modules never re-parse the environment."""
    return Settings()  # type: ignore[call-arg]

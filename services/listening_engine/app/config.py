"""
Centralized configuration for Termómetro Cultural.
Uses pydantic-settings with .env loading.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="termometro-cultural", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    database_url: str = Field(
        default="postgresql+asyncpg://localhost/termometro_cultural",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql://localhost/termometro_cultural",
        alias="DATABASE_URL_SYNC",
    )
    test_database_url: Optional[str] = Field(default=None, alias="TEST_DATABASE_URL")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    use_redis_queue: bool = Field(default=False, alias="USE_REDIS_QUEUE")

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    grok_api_key: Optional[str] = Field(default=None, alias="GROK_API_KEY")
    grok_model: str = Field(default="grok-2", alias="GROK_MODEL")

    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    proxy_rotation: bool = Field(default=False, alias="PROXY_ROTATION")
    proxy_list: str = Field(default="", alias="PROXY_LIST")

    municipality_name: str = Field(default="Tuluá", alias="MUNICIPALITY_NAME")
    municipality_region: str = Field(default="Valle del Cauca", alias="MUNICIPALITY_REGION")
    timezone: str = Field(default="America/Bogota", alias="TIMEZONE")

    # Scheduler
    scrape_interval_hours: int = Field(default=12, alias="SCRAPE_INTERVAL_HOURS")
    process_batch_size: int = Field(default=100, alias="PROCESS_BATCH_SIZE")

    # Retry (tenacity)
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_min_wait: float = Field(default=2.0, alias="RETRY_MIN_WAIT")
    retry_max_wait: float = Field(default=60.0, alias="RETRY_MAX_WAIT")

    # Rate limiting (per minute)
    llm_rate_limit_rpm: int = Field(default=60, alias="LLM_RATE_LIMIT_RPM")
    webhook_rate_limit_rpm: int = Field(default=30, alias="WEBHOOK_RATE_LIMIT_RPM")

    # Webhooks
    webhook_secret: Optional[str] = Field(default=None, alias="WEBHOOK_SECRET")

    # Telegram notifications
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # n8n webhook (push report after each scraping cycle)
    n8n_webhook_url: Optional[str] = Field(default=None, alias="N8N_WEBHOOK_URL")

    @property
    def proxy_urls(self) -> List[str]:
        if not self.proxy_list:
            return []
        return [p.strip() for p in self.proxy_list.split(",") if p.strip()]

    @model_validator(mode="after")
    def _default_test_database_url(self) -> "Settings":
        """Reuse the same asyncpg host as `database_url`, swapping only the db name."""
        if not self.test_database_url:
            base, _, _db_name = self.database_url.rpartition("/")
            self.test_database_url = f"{base}/termometro_cultural_test"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

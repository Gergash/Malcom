"""
config.py: configuración centralizada de la aplicación con Pydantic Settings.
Lee variables de entorno desde .env automáticamente.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_token: str = ""

    # Google Generative AI
    gemini_api_key: str = ""

    # PostgreSQL — formato: postgresql+asyncpg://user:password@host:port/dbname
    database_url: str = "postgresql+asyncpg://insightflow:insightflow@localhost:5432/insightflow"

    # Paywall
    free_message_limit: int = 15
    quota_timezone: str = "America/Bogota"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    # URL pública del API (ej. https://xxxx.ngrok-free.app — sin barra final).
    # Obligatoria si el front (WordPress) no puede alcanzar 127.0.0.1 ni si ngrok no envía X-Forwarded-*.
    public_base_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()

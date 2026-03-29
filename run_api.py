"""
run_api.py: entry point para el servidor FastAPI de InsightFlow.

Uso:
    python run_api.py

O directamente con uvicorn:
    uvicorn app.api.app:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
import sys
import os

# Asegura que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.dirname(__file__))

import uvicorn

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

if __name__ == "__main__":
    from app.core.config import get_settings

    settings = get_settings()

    uvicorn.run(
        "app.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )

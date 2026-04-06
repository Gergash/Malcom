"""
app.py: instancia principal de FastAPI con lifespan, middleware y rutas.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    from app.api.routes import billing, chat, health
    from app.database.connection import create_tables
except ModuleNotFoundError:
    from api.routes import billing, chat, health
    from database.connection import create_tables

logger = logging.getLogger(__name__)

# Raíz del proyecto Malcom (app/api/app.py → subir tres niveles)
MALCOM_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = MALCOM_ROOT / "data"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ejecutado al inicio y al cierre de la aplicación."""
    logger.info("InsightFlow API arrancando — creando tablas si no existen...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    await create_tables()
    logger.info("Base de datos lista.")
    yield
    logger.info("InsightFlow API cerrando.")


app = FastAPI(
    title="InsightFlow Malcom API",
    description=(
        "Motor de orquestación de agentes de análisis de datos. "
        "Recibe mensajes de usuarios, gestiona créditos en PostgreSQL "
        "y delega el análisis a los agentes de IA."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — ajusta origins según tu despliegue
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Archivos en data/{chat_id}/... servidos solo bajo /data (expuesto con cautela; no listado)
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# Rutas
app.include_router(health.router)
app.include_router(chat.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")

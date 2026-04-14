"""
worker.py: microservicio interno "InsightFlow-Brain".

Expone solo rutas /internal/* para que la API Go delegue orquestación e ingestión.
No debe exponerse a Internet; en Docker no se publica puerto hacia el host.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

try:
    from app.api.schemas import ReportConfig
    from app.core.orchestrator import Orchestrator
except ModuleNotFoundError:
    from api.schemas import ReportConfig
    from core.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="InsightFlow Brain",
    description="Worker interno: Orchestrator + agentes Python.",
    version="1.0.0",
)


class ProcessMessageRequest(BaseModel):
    chat_id: int = Field(..., description="ID de conversación / Telegram")
    message: str = Field(..., min_length=1)
    report_config: ReportConfig | None = None


class IngestFileRequest(BaseModel):
    chat_id: int
    tmp_path: str = Field(..., description="Ruta absoluta legible por este proceso (volumen compartido con Go)")
    filename: str


@app.get("/health")
async def health():
    return {"status": "ok", "service": "InsightFlow Brain"}


@app.post("/internal/process-message")
async def internal_process_message(body: ProcessMessageRequest):
    try:
        orch = Orchestrator(body.chat_id)
        result = await orch.process_message(body.message, report_config=body.report_config)
        return {
            "response":   result.get("response", ""),
            "has_pdf":    bool(result.get("has_pdf")),
            "has_excel":  bool(result.get("has_excel")),
            "has_chart":  bool(result.get("has_chart")),
            "chart_path": result.get("chart_path") or "",
            # Rutas absolutas para que el bot de Telegram pueda leer y enviar
            # los archivos directamente (volumen compartido en Docker).
            "pdf_path":   result.get("pdf_path") or "",
            "excel_path": result.get("excel_path") or "",
        }
    except Exception as exc:
        logger.exception("process-message chat_id=%s", body.chat_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/internal/ingest-file")
def internal_ingest_file(body: IngestFileRequest):
    if not body.tmp_path or not os.path.isfile(body.tmp_path):
        raise HTTPException(
            status_code=400,
            detail=f"Archivo temporal inexistente o no legible: {body.tmp_path!r}",
        )
    try:
        orch = Orchestrator(body.chat_id)
        result = orch.ingest_file(body.tmp_path, body.filename or "archivo")
        return {
            "saved_path": result.get("saved_path", ""),
            "indexed": bool(result.get("indexed")),
            "chunks": int(result.get("chunks") or 0),
            "message": result.get("message", ""),
            "error": result.get("error"),
        }
    except Exception as exc:
        logger.exception("ingest-file chat_id=%s", body.chat_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

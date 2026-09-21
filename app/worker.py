"""
worker.py: microservicio interno "InsightFlow-Brain".

Expone solo rutas /internal/* para que la API Go delegue orquestación e ingestión.
No debe exponerse a Internet; en Docker no se publica puerto hacia el host.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

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

# Límite duro por petición (segundos). Go también aplica context deadline.
_worker_timeout_sec = float(os.getenv("WORKER_REQUEST_TIMEOUT_SEC", "330"))

app = FastAPI(
    title="InsightFlow Brain",
    description="Worker interno: Orchestrator + agentes Python.",
    version="1.0.0",
)


class ProcessMessageRequest(BaseModel):
    chat_id: int = Field(..., description="ID de conversación / Telegram")
    message: str = Field(..., min_length=1)
    report_config: ReportConfig | None = None
    # True cuando la API Go detecta archivos en data/{chat_id}/ — no inventar datos.
    require_strict_data: bool = False
    # v2: ECharts para todos los usuarios cuando el Brain lo genera.
    generate_echarts: bool = False
    # Premium: habilita Termómetro Cultural / listening_engine.
    is_premium: bool = False
    # Saldo de créditos listening (API Go / Bold).
    listening_credits: int = 0


class IngestFileRequest(BaseModel):
    chat_id: int
    tmp_path: str = Field(..., description="Ruta absoluta legible por este proceso (volumen compartido con Go)")
    filename: str  # nombre en disco (p. ej. UUID + ext)
    original_filename: str | None = None  # nombre legible del usuario (índice RAG)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "InsightFlow Brain"}


class ListeningOverviewRequest(BaseModel):
    days: int | None = Field(None, ge=1, le=90)
    trigger_scrape: bool = False
    scrape_note: str | None = None


@app.post("/internal/listening/overview")
async def internal_listening_overview(body: ListeningOverviewRequest | None = None):
    """Overview chart-ready del Termómetro para la API Go / dashboard."""
    try:
        from app.listening.service import build_listening_overview
    except ModuleNotFoundError:
        from listening.service import build_listening_overview  # type: ignore

    req = body or ListeningOverviewRequest()
    try:
        result = await asyncio.wait_for(
            build_listening_overview(
                days=req.days,
                trigger_scrape=req.trigger_scrape,
                scrape_note=req.scrape_note,
            ),
            timeout=min(_worker_timeout_sec, 60.0),
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timeout al consultar el Termómetro.") from None
    except Exception:
        logger.exception("listening overview")
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener el overview del Termómetro Cultural.",
        ) from None

    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("response") or "listening-api no disponible",
        )
    return {
        "response": result.get("response", ""),
        "echarts_option": result.get("echarts_option"),
        "dashboard": result.get("dashboard"),
        "raw": result.get("raw"),
        "scraped": bool(result.get("scraped")),
        "source": "listening_engine",
    }


@app.post("/internal/process-message")
async def internal_process_message(body: ProcessMessageRequest):
    async def _run() -> dict[str, Any]:
        orch = Orchestrator(body.chat_id)
        result = await orch.process_message(
            body.message,
            report_config=body.report_config,
            require_strict_data=body.require_strict_data,
            generate_echarts=body.generate_echarts,
            is_premium=body.is_premium,
            listening_credits=body.listening_credits,
        )
        payload: dict[str, Any] = {
            "response": result.get("response", ""),
            "has_pdf": bool(result.get("has_pdf")),
            "has_excel": bool(result.get("has_excel")),
            "has_chart": bool(result.get("has_chart")),
            "chart_path": result.get("chart_path") or "",
            "pdf_path": result.get("pdf_path") or "",
            "excel_path": result.get("excel_path") or "",
        }
        eo = result.get("echarts_option")
        if eo is not None:
            payload["echarts_option"] = eo
        dash = result.get("dashboard")
        if dash is not None:
            payload["dashboard"] = dash
        if result.get("source"):
            payload["source"] = result["source"]
        for k in (
            "collection_phase",
            "listening_need_pack",
            "listening_need_credits",
            "listening_pack",
            "listening_credits_required",
            "listening_credits_charged",
            "listening_credits_balance",
            "scraped",
        ):
            if k in result:
                payload[k] = result[k]
        return payload

    try:
        return await asyncio.wait_for(_run(), timeout=_worker_timeout_sec)
    except asyncio.TimeoutError:
        logger.error("process-message timeout chat_id=%s", body.chat_id)
        raise HTTPException(
            status_code=504,
            detail="Tiempo de análisis agotado. Reduce el archivo o la pregunta e inténtalo de nuevo.",
        ) from None
    except Exception as exc:
        logger.exception("process-message chat_id=%s", body.chat_id)
        raise HTTPException(
            status_code=500,
            detail="No se pudo completar el análisis en este momento.",
        ) from exc


def _ingest_sync(body: IngestFileRequest) -> dict[str, Any]:
    orch = Orchestrator(body.chat_id)
    return orch.ingest_file(
        body.tmp_path,
        body.filename or "archivo",
        display_name=body.original_filename,
    )


@app.post("/internal/ingest-file")
async def internal_ingest_file(body: IngestFileRequest):
    if not body.tmp_path or not os.path.isfile(body.tmp_path):
        raise HTTPException(
            status_code=400,
            detail=f"Archivo temporal inexistente o no legible: {body.tmp_path!r}",
        )
    try:
        ingest_timeout = min(_worker_timeout_sec, 120.0)
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _ingest_sync(body)),
            timeout=ingest_timeout,
        )
        return {
            "saved_path": result.get("saved_path", ""),
            "indexed": bool(result.get("indexed")),
            "chunks": int(result.get("chunks") or 0),
            "message": result.get("message", ""),
            "error": result.get("error"),
        }
    except asyncio.TimeoutError:
        logger.error("ingest-file timeout chat_id=%s", body.chat_id)
        raise HTTPException(
            status_code=504,
            detail="Tiempo de ingestión agotado.",
        ) from None
    except Exception as exc:
        logger.exception("ingest-file chat_id=%s", body.chat_id)
        raise HTTPException(
            status_code=500,
            detail="No se pudo preparar el archivo en este momento.",
        ) from exc

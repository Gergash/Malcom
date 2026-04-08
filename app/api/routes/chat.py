"""
chat.py: endpoint principal de InsightFlow.

POST /api/v1/chat
  - Recibe el mensaje del usuario y su identidad.
  - Verifica y actualiza créditos en PostgreSQL.
  - Persiste el historial de conversación.
  - Delega el procesamiento al Orchestrator.
  - Devuelve la respuesta estructurada.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.api.schemas import ChatRequest, ChatResponse, CreditStateResponse, UploadResponse
    from app.core.config import get_settings
    from app.core.orchestrator import Orchestrator
    from app.database.connection import get_db
    from app.database.repositories.conversation_repo import ConversationRepository
    from app.database.repositories.user_repo import UserRepository
except ModuleNotFoundError:
    from api.schemas import ChatRequest, ChatResponse, CreditStateResponse, UploadResponse
    from core.config import get_settings
    from core.orchestrator import Orchestrator
    from database.connection import get_db
    from database.repositories.conversation_repo import ConversationRepository
    from database.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter()

# Raíz Malcom (app/api/routes/chat.py → cuatro niveles arriba)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _public_base_for_assets(request: Request) -> str:
    """
    Base URL que el *navegador del cliente* puede resolver (WordPress → img src).

    1) PUBLIC_BASE_URL en .env (recomendado con ngrok fijo o dominio).
    2) X-Forwarded-Proto + X-Forwarded-Host (túneles / reverse proxy que las envíen).
    3) request.base_url (solo válido si el cliente llama directamente a ese host).
    """
    settings = get_settings()
    explicit = (settings.public_base_url or "").strip().rstrip("/")
    if explicit:
        return explicit
    xf_proto = request.headers.get("x-forwarded-proto")
    xf_host = request.headers.get("x-forwarded-host")
    if xf_proto and xf_host:
        proto = xf_proto.split(",")[0].strip()
        host = xf_host.split(",")[0].strip()
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _chart_image_url(request: Request, chat_id: str, filename: str) -> str:
    base = _public_base_for_assets(request)
    url = f"{base}/data/{chat_id}/{filename}"
    # BLINDAJE CONTRA MIXED CONTENT: forzar HTTPS en dominios públicos
    if "ngrok" in url or "powerups.com" in url:
        url = url.replace("http://", "https://")
    return url


@router.post("/chat", response_model=ChatResponse, summary="Enviar mensaje al agente de análisis")
async def chat(
    payload: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint principal de conversación.

    Flujo:
    1. Verificar/crear usuario en PostgreSQL.
    2. Evaluar paywall (bump_and_check).
    3. Guardar mensaje del usuario en historial.
    4. Orquestar agentes (AnalystAgent / PredictorAgent).
    5. Guardar respuesta del asistente en historial.
    6. Retornar respuesta estructurada.
    """
    user_repo = UserRepository(db)
    conv_repo = ConversationRepository(db)

    # 1 + 2 · Verificar créditos
    credit_status = await user_repo.bump_and_check(
        chat_id=payload.chat_id,
        username=payload.username,
    )

    if credit_status["paywall"]:
        logger.info("Paywall alcanzado para chat_id=%s", payload.chat_id)
        return ChatResponse(
            response=(
                "Has alcanzado el límite gratuito de análisis.\n\n"
                "Activa el plan premium para desbloquear análisis ilimitados "
                "y reportes avanzados (PDF / Excel)."
            ),
            paywall=True,
            credits_remaining=0,
            image_url=None,
        )

    # 3 · Persistir mensaje del usuario
    await conv_repo.add_message(payload.chat_id, "user", payload.message)

    # 4 · Orquestar agentes
    try:
        orchestrator = Orchestrator(payload.chat_id)
        result = await orchestrator.process_message(payload.message)
    except Exception as exc:
        logger.exception("Error en Orchestrator para chat_id=%s", payload.chat_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando la consulta: {str(exc)}",
        ) from exc

    # 5 · Persistir respuesta del asistente
    await conv_repo.add_message(payload.chat_id, "assistant", result["response"])

    # 6 · URL pública de la gráfica (dominio ngrok / PUBLIC_BASE_URL, no 127.0.0.1)
    cid = str(payload.chat_id)
    image_url = None
    chart_disk = result.get("chart_path")
    if chart_disk and os.path.isfile(chart_disk):
        fname = os.path.basename(chart_disk)
        image_url = _chart_image_url(http_request, cid, fname)
    else:
        for fname in (f"output_plot_{cid}.png", "output_plot.png"):
            candidate = _PROJECT_ROOT / "data" / cid / fname
            if candidate.is_file():
                image_url = _chart_image_url(http_request, cid, fname)
                break

    return ChatResponse(
        response=result["response"],
        has_pdf=result["has_pdf"],
        has_excel=result["has_excel"],
        has_chart=result["has_chart"],
        paywall=False,
        credits_remaining=credit_status["credits_remaining"],
        image_url=image_url,
    )


@router.post("/chat/upload", response_model=UploadResponse, summary="Subir archivo para análisis")
async def upload_file(
    chat_id: int = Form(...),
    file: UploadFile = File(...),
):
    """
    Sube archivo para un usuario/canal y lo deja en data/{chat_id}/.
    Si el archivo es documental (PDF/DOCX/TXT), además lo indexa.
    """
    try:
        suffix = os.path.splitext(file.filename or "archivo")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            orchestrator = Orchestrator(chat_id)
            result = orchestrator.ingest_file(tmp_path, file.filename or "archivo")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except Exception as exc:
        logger.exception("Error subiendo archivo para chat_id=%s", chat_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo subir/procesar el archivo: {exc}",
        ) from exc

    return UploadResponse(
        chat_id=int(chat_id),
        filename=file.filename or "archivo",
        saved_path=result["saved_path"],
        indexed=bool(result["indexed"]),
        chunks=int(result["chunks"]),
        message=result["message"],
        error=result["error"],
    )


@router.get(
    "/chat/{chat_id}/credits",
    response_model=CreditStateResponse,
    summary="Consultar estado de créditos de un usuario",
)
async def get_credits(chat_id: int, db: AsyncSession = Depends(get_db)):
    """Devuelve el estado actual de créditos sin modificar el contador."""
    user_repo = UserRepository(db)
    state = await user_repo.get_state(chat_id)
    return CreditStateResponse(**state)

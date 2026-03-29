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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.api.schemas import ChatRequest, ChatResponse, CreditStateResponse
    from app.core.orchestrator import Orchestrator
    from app.database.connection import get_db
    from app.database.repositories.conversation_repo import ConversationRepository
    from app.database.repositories.user_repo import UserRepository
except ModuleNotFoundError:
    from api.schemas import ChatRequest, ChatResponse, CreditStateResponse
    from core.orchestrator import Orchestrator
    from database.connection import get_db
    from database.repositories.conversation_repo import ConversationRepository
    from database.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="Enviar mensaje al agente de análisis")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
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
        chat_id=request.chat_id,
        username=request.username,
    )

    if credit_status["paywall"]:
        logger.info("Paywall alcanzado para chat_id=%s", request.chat_id)
        return ChatResponse(
            response=(
                "Has alcanzado el límite gratuito de análisis.\n\n"
                "Activa el plan premium para desbloquear análisis ilimitados "
                "y reportes avanzados (PDF / Excel)."
            ),
            paywall=True,
            credits_remaining=0,
        )

    # 3 · Persistir mensaje del usuario
    await conv_repo.add_message(request.chat_id, "user", request.message)

    # 4 · Orquestar agentes
    try:
        orchestrator = Orchestrator(request.chat_id)
        result = await orchestrator.process_message(request.message)
    except Exception as exc:
        logger.exception("Error en Orchestrator para chat_id=%s", request.chat_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando la consulta: {str(exc)}",
        ) from exc

    # 5 · Persistir respuesta del asistente
    await conv_repo.add_message(request.chat_id, "assistant", result["response"])

    # 6 · Responder
    return ChatResponse(
        response=result["response"],
        has_pdf=result["has_pdf"],
        has_excel=result["has_excel"],
        has_chart=result["has_chart"],
        paywall=False,
        credits_remaining=credit_status["credits_remaining"],
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

"""
billing.py: endpoints de facturación e integración con el frontend WordPress.

GET  /api/v1/billing/status          → estado para el botón "Generar PDF Premium"
POST /api/v1/billing/webhook         → recibe confirmación de pago del PSP (Wompi/PSE)
POST /api/v1/billing/link-email      → vincula email a un chat_id de Telegram
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.api.schemas import (
        BillingStatusResponse,
        CreditStateResponse,
        PaymentWebhookRequest,
        PaymentWebhookResponse,
    )
    from app.database.connection import get_db
    from app.database.repositories.payment_repo import PaymentRepository
    from app.database.repositories.user_repo import UserRepository
except ModuleNotFoundError:
    from api.schemas import (
        BillingStatusResponse,
        CreditStateResponse,
        PaymentWebhookRequest,
        PaymentWebhookResponse,
    )
    from database.connection import get_db
    from database.repositories.payment_repo import PaymentRepository
    from database.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter()

# Precio de referencia en centavos ($40.000 COP)
PRICE_COP_CENTS = 4_000_000


# ── Estado de facturación ─────────────────────────────────────────────────────

@router.get(
    "/billing/status",
    response_model=BillingStatusResponse,
    summary="Estado de facturación del usuario (para WordPress)",
)
async def billing_status(
    chat_id: int | None = Query(None, description="Telegram chat_id del usuario"),
    email: str | None = Query(None, description="Email del usuario (alternativa al chat_id)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Consultado por el frontend de WordPress para decidir qué mostrar:
      - show_upgrade_button → True si el usuario es free (muestra el botón de compra)
      - show_pdf_button     → True si es premium (desbloquea el botón "Generar PDF")
      - paywall_active      → True si agotó los 7 mensajes gratuitos

    Requiere al menos uno: chat_id o email.
    """
    if chat_id is None and email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Se requiere al menos uno de: chat_id, email",
        )

    user_repo = UserRepository(db)
    state = await user_repo.get_state(chat_id=chat_id, email=email)

    is_premium: bool = state["is_premium"]
    return BillingStatusResponse(
        chat_id=state["chat_id"],
        email=state["email"],
        is_premium=is_premium,
        plan="premium" if is_premium else "free",
        message_count=state["message_count"],
        credits_remaining=state["credits_remaining"],
        show_upgrade_button=not is_premium,
        show_pdf_button=is_premium,
        paywall_active=state["paywall"],
        premium_since=state.get("premium_since"),
    )


# ── Webhook de pago ───────────────────────────────────────────────────────────

@router.post(
    "/billing/webhook",
    response_model=PaymentWebhookResponse,
    summary="Webhook de confirmación de pago (PSP → InsightFlow)",
)
async def payment_webhook(
    payload: PaymentWebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Recibe la notificación de pago del PSP (Wompi, PSE u otro).

    Flujo:
      APPROVED → marca payment como 'paid' + activa is_premium en el usuario.
      DECLINED / ERROR / VOIDED → registra el pago como 'failed'.

    Es idempotente: si la misma referencia ya fue procesada, responde
    success=True + already_processed=True sin modificar nada.

    Configuración en Wompi:
      URL de eventos: https://tu-dominio.com/api/v1/billing/webhook
    """
    payment_repo = PaymentRepository(db)
    approved_statuses = {"APPROVED", "approved", "COMPLETED", "completed"}

    if payload.status.upper() not in {s.upper() for s in approved_statuses}:
        # Pago fallido — registrar pero no activar premium
        payment = await payment_repo.mark_failed(
            reference=payload.reference,
            provider=payload.provider,
            amount_cop=payload.amount_in_cents,
        )
        logger.warning(
            "Pago rechazado | ref=%s | status=%s | provider=%s",
            payload.reference, payload.status, payload.provider,
        )
        return PaymentWebhookResponse(
            success=False,
            message=f"Pago con estado '{payload.status}' registrado.",
            reference=payload.reference,
        )

    # Pago aprobado
    result = await payment_repo.confirm_payment(
        reference=payload.reference,
        amount_cop=payload.amount_in_cents,
        provider=payload.provider,
        payer_email=payload.payer_email,
        payer_chat_id=payload.payer_chat_id,
    )

    user = result["user"]
    already = result["already_processed"]

    logger.info(
        "Pago confirmado | ref=%s | email=%s | chat_id=%s | ya_procesado=%s",
        payload.reference,
        payload.payer_email,
        payload.payer_chat_id,
        already,
    )

    return PaymentWebhookResponse(
        success=True,
        already_processed=already,
        message="Premium activado." if not already else "Pago ya procesado anteriormente.",
        reference=payload.reference,
        user_email=user.email if user else None,
        user_chat_id=user.chat_id if user else None,
        is_premium=user.is_premium if user else False,
    )


# ── Vincular email a Telegram ─────────────────────────────────────────────────

@router.post(
    "/billing/link-email",
    response_model=CreditStateResponse,
    summary="Vincula un email permanente al chat_id de Telegram del usuario",
)
async def link_email(
    chat_id: int = Body(..., embed=True),
    email: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Asocia el email del usuario (identidad web/pago) con su chat_id de Telegram.
    Necesario para que el webhook de pago pueda activar el premium
    aunque no llegue el chat_id en el payload.

    Llamado desde el bot cuando el usuario escribe /email o desde el
    formulario de registro del frontend WordPress.
    """
    user_repo = UserRepository(db)
    try:
        await user_repo.link_email(chat_id=chat_id, email=email)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pudo vincular el email: {exc}",
        ) from exc

    state = await user_repo.get_state(chat_id=chat_id)
    return CreditStateResponse(**state)

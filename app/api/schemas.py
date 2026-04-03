"""
schemas.py: modelos Pydantic para request/response del API.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    chat_id: int = Field(..., description="ID único del usuario (Telegram chat_id u otro canal)")
    message: str = Field(..., min_length=1, description="Texto del mensaje del usuario")
    username: Optional[str] = Field(None, description="Nombre de usuario (opcional, para registro)")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Respuesta generada por el agente")
    has_pdf: bool = Field(False, description="¿Se generó un reporte PDF?")
    has_excel: bool = Field(False, description="¿Se generó un reporte Excel?")
    has_chart: bool = Field(False, description="¿Se generó una imagen de gráfica?")
    paywall: bool = Field(False, description="True si el usuario alcanzó el límite gratuito")
    credits_remaining: int = Field(0, description="Mensajes gratuitos restantes (-1 = premium)")


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    chat_id: int
    filename: str
    saved_path: str
    indexed: bool
    chunks: int = 0
    message: str
    error: Optional[str] = None


# ── Credits ───────────────────────────────────────────────────────────────────

class CreditStateResponse(BaseModel):
    chat_id: Optional[int]
    email: Optional[str]
    username: Optional[str]
    message_count: int
    is_premium: bool
    free_message_limit: int
    credits_remaining: int
    paywall: bool
    premium_since: Optional[str] = None


# ── Billing ───────────────────────────────────────────────────────────────────

class BillingStatusResponse(BaseModel):
    """
    Respuesta que el frontend de WordPress consulta para decidir
    qué botones mostrar al usuario.
    """
    chat_id: Optional[int] = None
    email: Optional[str] = None
    is_premium: bool
    plan: str                        # 'free' | 'premium'
    message_count: int
    credits_remaining: int
    # Flags para el frontend
    show_upgrade_button: bool        # True si el usuario no es premium
    show_pdf_button: bool            # True si el usuario es premium (PDF desbloqueado)
    paywall_active: bool             # True si ya agotó los mensajes gratuitos
    premium_since: Optional[str] = None


class PaymentWebhookRequest(BaseModel):
    """
    Payload que envía el PSP (Wompi/PSE/WooCommerce) a
    POST /api/v1/billing/webhook cuando un pago es aprobado o rechazado.

    Los campos siguen la estructura de Wompi Colombia,
    pero son suficientemente genéricos para otros proveedores.
    """
    reference: str = Field(..., description="Referencia única del pago generada por WordPress")
    status: str = Field(..., description="'APPROVED' | 'DECLINED' | 'ERROR' | 'VOIDED'")
    amount_in_cents: int = Field(..., description="Monto en centavos COP (4000000 = $40.000)")
    provider: str = Field("wompi", description="Proveedor de pago")
    payer_email: Optional[str] = Field(None, description="Email del pagador")
    payer_chat_id: Optional[int] = Field(None, description="chat_id de Telegram del pagador (si aplica)")


class PaymentWebhookResponse(BaseModel):
    success: bool
    already_processed: bool = False
    message: str
    reference: str
    user_email: Optional[str] = None
    user_chat_id: Optional[int] = None
    is_premium: bool = False


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str

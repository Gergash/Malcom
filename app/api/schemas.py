"""
schemas.py: modelos Pydantic para request/response del API.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    chat_id: int = Field(..., description="ID único del usuario (Telegram chat_id u otro canal)")
    message: str = Field(..., min_length=1, description="Texto del mensaje del usuario")
    username: Optional[str] = Field(None, description="Nombre de usuario (opcional, para registro)")


# ── Responses ─────────────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    response: str = Field(..., description="Respuesta generada por el agente")
    has_pdf: bool = Field(False, description="¿Se generó un reporte PDF?")
    has_excel: bool = Field(False, description="¿Se generó un reporte Excel?")
    has_chart: bool = Field(False, description="¿Se generó una imagen de gráfica?")
    paywall: bool = Field(False, description="True si el usuario alcanzó el límite gratuito")
    credits_remaining: int = Field(0, description="Mensajes gratuitos restantes (-1 = premium)")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class CreditStateResponse(BaseModel):
    chat_id: int
    message_count: int
    is_premium: bool
    free_message_limit: int
    credits_remaining: int
    paywall: bool

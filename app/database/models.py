"""
models.py: modelos ORM de SQLAlchemy para PostgreSQL.

Tablas:
  - users         → identidad (email + chat_id), plan premium y contador (paywall)
  - conversations → historial de mensajes por chat_id
  - user_files    → archivos subidos vinculados al usuario real (data/{chat_id}/)
  - payments      → registro de webhooks de pago ($40.000 COP → premium)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Identidad Telegram (volátil — puede ser None si el usuario llega por web)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    # Identidad web permanente — ancla para el webhook de pago y el frontend WordPress
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Paywall
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    free_message_limit: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    # Fecha en que se activó el plan premium (útil para métricas de retención)
    premium_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # 'user' | 'assistant'
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class UserFile(Base):
    """
    Vincula los archivos de data/{chat_id}/ con un usuario real de la BD.
    Permite al frontend web mostrar los archivos propios del usuario
    y garantizar la soberanía de datos (Ley 1581 Colombia).
    """

    __tablename__ = "user_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # 'csv' | 'xlsx' | 'pdf' | 'docx' | 'txt' | 'other'
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True si fue indexado por KnowledgeAgent (embeddings generados)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Payment(Base):
    """
    Registro de pagos recibidos vía webhook ($40.000 COP → premium).

    El flujo es:
      1. WordPress genera referencia única y redirige al PSP (Wompi/PSE).
      2. PSP notifica nuestro POST /api/v1/billing/webhook con status APPROVED.
      3. Marcamos el pago como 'paid' y activamos is_premium en el usuario.

    El campo `user_id` puede ser NULL si el pago llega antes de que el usuario
    exista en la BD (caso web sin Telegram previo); se vincula en el webhook.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Referencia única generada por WordPress / PSP
    reference: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    # Monto en pesos colombianos (centavos para Wompi: 4000000 = $40.000)
    amount_cop: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'pending' | 'paid' | 'failed' | 'refunded'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Proveedor de pago: 'wompi', 'pse', 'woocommerce', 'manual', etc.
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="wompi")
    # Email del pagador (clave de vinculación con users.email)
    payer_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    # chat_id del pagador (alternativa cuando viene por Telegram)
    payer_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

"""
payment_repo.py: CRUD sobre la tabla `payments`.

Gestiona el ciclo de vida de un pago:
  pending → paid (webhook APPROVED) → activa is_premium en el usuario.
  pending → failed (webhook DECLINED/ERROR)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.database.models import Payment, User
    from app.database.repositories.user_repo import UserRepository
except ModuleNotFoundError:
    from database.models import Payment, User
    from database.repositories.user_repo import UserRepository


class PaymentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_reference(self, reference: str) -> Payment | None:
        result = await self.db.execute(
            select(Payment).where(Payment.reference == reference)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        reference: str,
        amount_cop: int,
        provider: str = "wompi",
        payer_email: str | None = None,
        payer_chat_id: int | None = None,
        status: str = "pending",
    ) -> Payment:
        """Registra un nuevo intento de pago (estado inicial: pending)."""
        payment = Payment(
            reference=reference,
            amount_cop=amount_cop,
            provider=provider,
            payer_email=payer_email.lower().strip() if payer_email else None,
            payer_chat_id=payer_chat_id,
            status=status,
        )
        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)
        return payment

    async def confirm_payment(
        self,
        reference: str,
        amount_cop: int,
        provider: str,
        payer_email: str | None = None,
        payer_chat_id: int | None = None,
    ) -> dict:
        """
        Procesa un webhook de pago aprobado:
          1. Busca o crea el registro de pago.
          2. Marca el pago como 'paid'.
          3. Vincula al usuario (por email o chat_id).
          4. Activa is_premium en el usuario.

        Retorna:
            {
                "payment": Payment,
                "user": User,
                "already_processed": bool,
            }
        """
        user_repo = UserRepository(self.db)

        # Idempotencia: no procesar dos veces la misma referencia
        payment = await self.get_by_reference(reference)
        if payment is not None and payment.status == "paid":
            user = None
            if payment.user_id:
                result = await self.db.execute(
                    select(User).where(User.id == payment.user_id)
                )
                user = result.scalar_one_or_none()
            return {"payment": payment, "user": user, "already_processed": True}

        # Crear si no existe
        if payment is None:
            payment = await self.create(
                reference=reference,
                amount_cop=amount_cop,
                provider=provider,
                payer_email=payer_email,
                payer_chat_id=payer_chat_id,
                status="pending",
            )

        # Activar premium en el usuario
        user = await user_repo.activate_premium(
            chat_id=payer_chat_id,
            email=payer_email,
        )

        # Actualizar pago
        payment.status = "paid"
        payment.user_id = user.id
        payment.paid_at = datetime.utcnow()
        if payer_email and not payment.payer_email:
            payment.payer_email = payer_email.lower().strip()
        if payer_chat_id and not payment.payer_chat_id:
            payment.payer_chat_id = payer_chat_id
        await self.db.commit()
        await self.db.refresh(payment)

        return {"payment": payment, "user": user, "already_processed": False}

    async def mark_failed(self, reference: str, provider: str, amount_cop: int) -> Payment:
        """Registra un pago fallido/rechazado."""
        payment = await self.get_by_reference(reference)
        if payment is None:
            payment = await self.create(
                reference=reference,
                amount_cop=amount_cop,
                provider=provider,
                status="failed",
            )
        else:
            payment.status = "failed"
            await self.db.commit()
            await self.db.refresh(payment)
        return payment

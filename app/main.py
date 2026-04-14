"""
main.py: bot de Telegram de InsightFlow.

Cambios respecto a la versión anterior:
- Ya NO instancia Orchestrator / AnalystAgent / PredictorAgent directamente.
- Delega el procesamiento de mensajes e ingestión de archivos al Worker
  interno (app/worker.py) mediante llamadas HTTP a /internal/*.
- Mantiene la gestión de créditos/paywall vía SQLAlchemy (PostgreSQL).
- Bug corregido: las gráficas se leen desde chart_path devuelto por el
  worker (data/{chat_id}/output_plot_{chat_id}.png), no desde el CWD.
"""

from __future__ import annotations

import logging
import os

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from app.database.connection import AsyncSessionLocal, create_tables
    from app.database.repositories.conversation_repo import ConversationRepository
    from app.database.repositories.user_repo import UserRepository
except ModuleNotFoundError:
    from database.connection import AsyncSessionLocal, create_tables
    from database.repositories.conversation_repo import ConversationRepository
    from database.repositories.user_repo import UserRepository

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
WORKER_URL = os.getenv("WORKER_URL", "http://localhost:8001").rstrip("/")
DATA_DIR = os.getenv("DATA_DIR", "data")

TELEGRAM_MAX_CHARS = 4096
SEND_CHUNK_SIZE = TELEGRAM_MAX_CHARS - 30

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── Cliente HTTP → Worker ─────────────────────────────────────────────────────

async def _worker_process(chat_id: int, message: str) -> dict:
    """POST /internal/process-message → devuelve response + artefactos."""
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{WORKER_URL}/internal/process-message",
            json={"chat_id": chat_id, "message": message},
        )
        resp.raise_for_status()
        return resp.json()


async def _worker_ingest(chat_id: int, file_path: str, filename: str) -> dict:
    """POST /internal/ingest-file → indexa el archivo ya guardado en disco."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{WORKER_URL}/internal/ingest-file",
            json={"chat_id": chat_id, "tmp_path": file_path, "filename": filename},
        )
        resp.raise_for_status()
        return resp.json()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_long(bot, chat_id: int, text: str) -> None:
    """Parte texto en bloques si supera el límite de Telegram (4096 chars)."""
    text = (text or "").strip()
    while text:
        chunk = text[:SEND_CHUNK_SIZE]
        if len(text) > SEND_CHUNK_SIZE:
            cut = chunk.rfind("\n")
            if cut > SEND_CHUNK_SIZE // 2:
                chunk = chunk[: cut + 1]
        await bot.send_message(chat_id=chat_id, text=chunk)
        text = text[len(chunk):].lstrip()


# ── Handlers de Telegram ──────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"¡Hola {name}! Bienvenido a InsightFlow.\n"
            "Envíame un mensaje o un archivo para comenzar el análisis."
        ),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    filename = update.message.document.file_name or "archivo"

    # Guardar el archivo en data/{chat_id}/ (mismo volumen que el worker en Docker)
    user_dir = os.path.join(DATA_DIR, str(chat_id))
    os.makedirs(user_dir, exist_ok=True)
    save_path = os.path.abspath(os.path.join(user_dir, filename))

    tg_file = await update.message.document.get_file()
    await tg_file.download_to_drive(save_path)
    logger.info("Archivo chat_id=%s guardado en: %s", chat_id, save_path)

    try:
        result = await _worker_ingest(chat_id, save_path, filename)
        await update.message.reply_text(
            f"✅ {result.get('message', 'Archivo recibido.')}\n"
            "Ya puedes pedirme el análisis."
        )
    except Exception as exc:
        logger.exception("Error ingesting file chat_id=%s", chat_id)
        await update.message.reply_text(
            f"✅ Archivo '{filename}' recibido.\n⚠️ Error al procesar: {exc}"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name

    # ── Créditos / paywall (SQLAlchemy — igual que antes) ─────────────────────
    async with AsyncSessionLocal() as db:
        user_repo = UserRepository(db)
        conv_repo = ConversationRepository(db)

        credit_status = await user_repo.bump_and_check(chat_id=chat_id, username=username)
        if credit_status["paywall"]:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "Has alcanzado el límite gratuito de análisis.\n\n"
                    "Activa el plan premium para desbloquear análisis ilimitados "
                    "y reportes avanzados (PDF/Excel)."
                ),
            )
            return

        await conv_repo.add_message(chat_id, "user", user_text)

    logger.info("Consulta chat_id=%s: %.80s", chat_id, user_text)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # ── Llamar al Worker (Orchestrator en proceso separado) ────────────────────
    try:
        result = await _worker_process(chat_id, user_text)
    except Exception as exc:
        logger.exception("Worker error chat_id=%s", chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Tuvimos un problema técnico: {exc}",
        )
        return

    response_text = result.get("response", "")

    # ── Persistir respuesta del asistente ──────────────────────────────────────
    async with AsyncSessionLocal() as db:
        conv_repo = ConversationRepository(db)
        await conv_repo.add_message(chat_id, "assistant", response_text or "")

    await _send_long(context.bot, chat_id, response_text)

    # ── Artefacto: PDF ─────────────────────────────────────────────────────────
    pdf_path = result.get("pdf_path") or ""
    if result.get("has_pdf") and pdf_path and os.path.isfile(pdf_path):
        try:
            with open(pdf_path, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc,
                    filename="reporte_final.pdf",
                    caption="📄 Informe PDF generado por InsightFlow.",
                )
            os.remove(pdf_path)
        except Exception as exc:
            logger.warning("No se pudo enviar PDF: %s", exc)

    # ── Artefacto: Excel ───────────────────────────────────────────────────────
    excel_path = result.get("excel_path") or ""
    if result.get("has_excel") and excel_path and os.path.isfile(excel_path):
        try:
            with open(excel_path, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc,
                    filename="reporte_final.xlsx",
                    caption="📊 Informe Excel generado por InsightFlow.",
                )
            os.remove(excel_path)
        except Exception as exc:
            logger.warning("No se pudo enviar Excel: %s", exc)

    # ── Artefacto: Gráfica ─────────────────────────────────────────────────────
    # BUG FIX: se usaba os.path.exists(f"output_plot_{chat_id}.png") que buscaba
    # en el CWD raíz. Ahora se usa chart_path del worker, que apunta correctamente
    # a data/{chat_id}/output_plot_{chat_id}.png.
    chart_path = result.get("chart_path") or ""
    if result.get("has_chart") and chart_path and os.path.isfile(chart_path):
        try:
            with open(chart_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption="📊 Análisis visual generado por InsightFlow.",
                )
            os.remove(chart_path)
        except Exception as exc:
            logger.warning("No se pudo enviar gráfica: %s", exc)


# ── Arranque ──────────────────────────────────────────────────────────────────

async def post_init(application) -> None:
    await create_tables()
    logger.info("Tablas PostgreSQL listas.")


if __name__ == "__main__":
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("InsightFlow Bot arrancando — WORKER_URL=%s", WORKER_URL)
    application.run_polling()

import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

try:
    from app.agents.analyst_agent import AnalystAgent
    from app.agents.predictor_agent import PredictorAgent
    from app.agents.knowledge_agent import DOC_EXTENSIONS
    from app.database.connection import AsyncSessionLocal, create_tables
    from app.database.repositories.user_repo import UserRepository
    from app.database.repositories.conversation_repo import ConversationRepository
except ModuleNotFoundError:
    from agents.analyst_agent import AnalystAgent
    from agents.predictor_agent import PredictorAgent
    from agents.knowledge_agent import DOC_EXTENSIONS
    from database.connection import AsyncSessionLocal, create_tables
    from database.repositories.user_repo import UserRepository
    from database.repositories.conversation_repo import ConversationRepository

TELEGRAM_MAX_CHARS = 4096
SEND_CHUNK_SIZE = TELEGRAM_MAX_CHARS - 30

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

agent = AnalystAgent()
predictor = PredictorAgent()


async def _send_long_message(bot, chat_id: int, text: str):
    """Envía un texto que puede superar el límite de Telegram, partiéndolo en bloques."""
    if not text:
        return
    text = text.strip()
    while text:
        chunk = text[:SEND_CHUNK_SIZE] if len(text) > SEND_CHUNK_SIZE else text
        if len(text) > SEND_CHUNK_SIZE:
            last_nl = chunk.rfind("\n")
            if last_nl > SEND_CHUNK_SIZE // 2:
                chunk = chunk[: last_nl + 1]
        await bot.send_message(chat_id=chat_id, text=chunk)
        text = text[len(chunk):].lstrip()


PREDICTION_KEYWORDS = (
    "stock", "comprar", "buy", "cuánto", "how much", "pronóstico", "forecast",
    "recomendación", "recommend", "inventory", "inventario", "pedido", "order",
    "esta semana", "this week", "semanas", "weeks"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"¡Hola {user_name}! Bienvenido a InsightFlow. Envíame un mensaje o un archivo para comenzar el análisis."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    filename = update.message.document.file_name
    chat_id = update.effective_chat.id

    relative_path = f"data/{chat_id}/{filename}"
    full_path = os.path.abspath(relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    await file.download_to_drive(full_path)
    print(f"DEBUG: Archivo de {chat_id} guardado en: {full_path}")

    _suffix = os.path.splitext(filename)[1].lower() if filename else ""
    if _suffix in DOC_EXTENSIONS:
        knowledge_agent = agent.get_knowledge_agent(chat_id)
        try:
            n_chunks, err = knowledge_agent.index_file(full_path, source_id=filename)
            if err:
                await update.message.reply_text(
                    f"✅ Archivo '{filename}' recibido.\n⚠️ No se pudo indexar para búsqueda: {err}"
                )
            else:
                await update.message.reply_text(
                    f"✅ Archivo '{filename}' recibido e indexado ({n_chunks} fragmentos).\n"
                    "Lo usaré para enriquecer el análisis de tus datos.\n"
                    "Ya puedes pedirme el análisis o las gráficas que necesites."
                )
        except Exception as e:
            print(f"DEBUG: Error indexando documento: {e}")
            await update.message.reply_text(
                f"✅ Archivo '{filename}' recibido.\n⚠️ Error al indexar: {str(e)}"
            )
    else:
        await update.message.reply_text(
            f"✅ Archivo '{filename}' recibido.\n"
            "Ya puedes pedirme el análisis o las gráficas que necesites."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name

    # ── Créditos / paywall via PostgreSQL ──────────────────────────────────
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

        # Persistir mensaje del usuario
        await conv_repo.add_message(chat_id, "user", user_text)

    user_data_folder = os.path.abspath(f"data/{chat_id}")

    print(f"\n--- NUEVA CONSULTA ---")
    print(f"Usuario {chat_id} ({username}) dice: {user_text}")
    print(f"Carpeta usuario: {user_data_folder}")

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        is_prediction = any(kw in user_text.lower() for kw in PREDICTION_KEYWORDS)
        if is_prediction:
            respuesta_ia = predictor.answer_business_question(
                user_text,
                local_file_path=None,
                user_data_folder=user_data_folder,
            )
        else:
            respuesta_ia = await agent.analyze_data(
                user_text,
                local_file_path=None,
                user_data_folder=user_data_folder,
                chat_id=chat_id,
            )

        await _send_long_message(context.bot, chat_id, respuesta_ia)

        # ── Persistir respuesta del asistente ─────────────────────────────
        async with AsyncSessionLocal() as db:
            conv_repo = ConversationRepository(db)
            await conv_repo.add_message(chat_id, "assistant", respuesta_ia or "")

        # ── Enviar artefactos generados ────────────────────────────────────
        pdf_report_path = agent.peek_pending_pdf_report()
        if pdf_report_path and os.path.isfile(pdf_report_path):
            try:
                with open(pdf_report_path, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=doc,
                        filename="reporte_final.pdf",
                        caption="📄 Informe PDF generado por InsightFlow.",
                    )
                os.remove(pdf_report_path)
            except Exception as pdf_err:
                logging.warning("No se pudo enviar reporte_final.pdf: %s", pdf_err)
            finally:
                agent.clear_pending_pdf_report()

        excel_report_path = agent.peek_pending_excel_report()
        if excel_report_path and os.path.isfile(excel_report_path):
            try:
                with open(excel_report_path, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=doc,
                        filename="reporte_final.xlsx",
                        caption="📊 Informe Excel generado por InsightFlow.",
                    )
                os.remove(excel_report_path)
            except Exception as xlsx_err:
                logging.warning("No se pudo enviar reporte_final.xlsx: %s", xlsx_err)
            finally:
                agent.clear_pending_excel_report()

        plot_filename = f"output_plot_{chat_id}.png"
        await asyncio.sleep(1)

        if os.path.exists(plot_filename):
            print(f"LOG: ¡Gráfica encontrada! Enviando a Telegram ({plot_filename})...")
            with open(plot_filename, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption="📊 Análisis visual generado por InsightFlow."
                )
            os.remove(plot_filename)
        else:
            if "grafic" in user_text.lower() or "dibuj" in user_text.lower():
                print(f"LOG: El usuario pidió gráfica pero '{plot_filename}' no fue creado.")

    except Exception as e:
        print(f"ERROR en handle_message: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Tuvimos un problema técnico: {str(e)}"
        )


async def post_init(application):
    """Inicializa las tablas de PostgreSQL al arrancar el bot."""
    await create_tables()
    logging.info("Tablas PostgreSQL listas.")


if __name__ == '__main__':
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("InsightFlow Bot corriendo y escuchando archivos...")
    application.run_polling()

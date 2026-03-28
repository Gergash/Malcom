import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from agents.analyst_agent import AnalystAgent
from agents.credits import check_and_bump
try:
    # `python -m app.main`
    from app.database.quota_manager import QuotaManager
except ModuleNotFoundError:
    # `python main.py` desde `app/`
    from database.quota_manager import QuotaManager
from agents.predictor_agent import PredictorAgent
from agents.knowledge_agent import DOC_EXTENSIONS
import asyncio

TELEGRAM_MAX_CHARS = 4096
SEND_CHUNK_SIZE = TELEGRAM_MAX_CHARS - 30

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"¡Hola {user_name}! Bienvenido a InsightFlow. Envíame un mensaje o un archivo para comenzar el análisis."
    )


agent = AnalystAgent()
predictor = PredictorAgent()
quota = QuotaManager()

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
        text = text[len(chunk) :].lstrip()


PREDICTION_KEYWORDS = (
    "stock", "comprar", "buy", "cuánto", "how much", "pronóstico", "forecast",
    "recomendación", "recommend", "inventory", "inventario", "pedido", "order",
    "esta semana", "this week", "semanas", "weeks"
)

async def handle_document(update, context):
    file = await update.message.document.get_file()
    filename = update.message.document.file_name
    chat_id = update.effective_chat.id

    relative_path = f"data/{chat_id}/{filename}"
    full_path = os.path.abspath(relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    await file.download_to_drive(full_path)
    context.user_data['current_file'] = full_path
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
                    "Lo usaré para enriquecer el análisis de tus datos (ej. reportes, reglas de negocio).\n"
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

    # Créditos / paywall (lógica comercial modular)
    # - Si no es premium y supera el límite, cortamos antes de consumir análisis.
    paywall = check_and_bump(quota, chat_id)
    if paywall == "PAYWALL_TRIGGER":
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Has alcanzado el límite gratuito de análisis.\n\n"
                "Si deseas continuar, activa el plan premium para desbloquear análisis ilimitados "
                "y reportes avanzados (PDF/Excel)."
            ),
        )
        return

    user_data_folder = os.path.abspath(f"data/{chat_id}")
    file_path = context.user_data.get("current_file")

    print(f"\n--- NUEVA CONSULTA ---")
    print(f"Usuario {chat_id} dice: {user_text}")
    print(f"Carpeta usuario: {user_data_folder}")
    print(f"Archivo actual: {file_path}")

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        is_prediction = any(kw in user_text.lower() for kw in PREDICTION_KEYWORDS)
        if is_prediction:
            respuesta_ia = predictor.answer_business_question(
                user_text,
                local_file_path=file_path,
                user_data_folder=user_data_folder,
            )
        else:
            respuesta_ia = await agent.analyze_data(
                user_text,
                local_file_path=file_path,
                user_data_folder=user_data_folder,
                chat_id=chat_id,
            )
        await _send_long_message(context.bot, chat_id, respuesta_ia)

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
        print(f"DEBUG: ¿Existe el archivo de imagen? {os.path.exists(plot_filename)}")
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
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Tuvimos un problema técnico: {str(e)}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("InsightFlow Bot corriendo y escuchando archivos...")
    application.run_polling()

import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from agents.analyst_agent import AnalystAgent
from agents.predictor_agent import PredictorAgent
from agents.knowledge_agent import KnowledgeAgent, DOC_EXTENSIONS
import asyncio

# Telegram permite 4096 caracteres por mensaje; enviamos en bloques para no superar el límite
TELEGRAM_MAX_CHARS = 4096
SEND_CHUNK_SIZE = TELEGRAM_MAX_CHARS - 30  # 4066

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Configuración de logs para ver errores en consola
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Función para el comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"¡Hola {user_name}! Bienvenido a InsightFlow. Envíame un mensaje o un archivo para comenzar el análisis."
    )


# Base vectorial: data/vector_db (relativa a la raíz del proyecto Malcom)
_vector_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "vector_db"))
knowledge_agent = KnowledgeAgent(vector_db_path=_vector_db_path)
agent = AnalystAgent(knowledge_agent=knowledge_agent)
predictor = PredictorAgent()

async def _send_long_message(bot, chat_id: int, text: str):
    """Envía un texto que puede superar el límite de Telegram, partiéndolo en mensajes de SEND_CHUNK_SIZE."""
    if not text:
        return
    text = text.strip()
    while text:
        chunk = text[:SEND_CHUNK_SIZE] if len(text) > SEND_CHUNK_SIZE else text
        if len(text) > SEND_CHUNK_SIZE:
            # Cortar en el último salto de línea para no partir palabras
            last_nl = chunk.rfind("\n")
            if last_nl > SEND_CHUNK_SIZE // 2:
                chunk = chunk[: last_nl + 1]
        await bot.send_message(chat_id=chat_id, text=chunk)
        text = text[len(chunk) :].lstrip()


# Keywords that route to the predictor (business/recommendation questions)
PREDICTION_KEYWORDS = (
    "stock", "comprar", "buy", "cuánto", "how much", "pronóstico", "forecast",
    "recomendación", "recommend", "inventory", "inventario", "pedido", "order",
    "esta semana", "this week", "semanas", "weeks"
)

async def handle_document(update, context):
    file = await update.message.document.get_file()    
    # 1. Definimos una ruta absoluta para evitar confusiones de carpetas
    filename = update.message.document.file_name
    chat_id = update.effective_chat.id
    # Creamos la ruta completa
    relative_path = f"data/{chat_id}/{filename}"
    full_path = os.path.abspath(relative_path) # <-- DIFERENCIA: Ruta absoluta
    # 2. Creamos los directorios si no existen
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    # 3. Descargamos el archivo
    await file.download_to_drive(full_path)
    # 4. Guardamos la ruta en context.user_data para que handle_message la encuentre
    context.user_data['current_file'] = full_path
    print(f"DEBUG: Archivo de {chat_id} guardado físicamente en: {full_path}")

    # 5. Si es PDF, DOCX o TXT, indexar en la base vectorial para búsqueda semántica
    _suffix = os.path.splitext(filename)[1].lower() if filename else ""
    if _suffix in DOC_EXTENSIONS:
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
    
    # Carpeta exclusiva de este usuario: data/{chat_id}. Ahí se guardan sus archivos.
    user_data_folder = os.path.abspath(f"data/{chat_id}")
    file_path = context.user_data.get("current_file")
    
    print(f"\n--- NUEVA CONSULTA ---")
    print(f"Usuario {chat_id} dice: {user_text}")
    print(f"Carpeta usuario: {user_data_folder}")
    print(f"Archivo actual: {file_path}")
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Route: preguntas de recomendación -> PredictorAgent, resto -> AnalystAgent
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
        # 2. Enviamos el texto (en uno o varios mensajes si supera el límite de Telegram)
        await _send_long_message(context.bot, chat_id, respuesta_ia)
        # 3. Pequeña pausa de seguridad para que el sistema de archivos asiente la imagen
        plot_filename = f"output_plot_{chat_id}.png"
        print(f"DEBUG: ¿Existe el archivo de imagen? {os.path.exists(plot_filename)}")
        await asyncio.sleep(1)

        # 4. Verificación y envío de la imagen
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
    # IMPORTANTE: El orden importa. Primero comandos, luego documentos, luego texto.
    application.add_handler(CommandHandler('start', start))
    # Esta es la línea que probablemente te falta:
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("InsightFlow Bot corriendo y escuchando archivos...")
    application.run_polling()

# En la sección de handlers agregarías:
# application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
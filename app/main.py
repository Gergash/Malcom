import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from agents.analyst_agent import AnalystAgent
# ... (importaciones anteriores)


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


# ... (importaciones y configuración de logging)

agent = AnalystAgent()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # Llamada al agente
        respuesta_ia = await agent.analyze_data(user_text)
        await context.bot.send_message(chat_id=chat_id, text=respuesta_ia)
        
        # Lógica de la gráfica (opcional)
        if os.path.exists("output_plot.png"):
            with open("output_plot.png", "rb") as photo:
                await context.bot.send_photo(chat_id=chat_id, photo=photo)
            os.remove("output_plot.png")
            
    except Exception as e:
        # Esto te avisará en Telegram cuál es el error exacto
        error_msg = f"Hubo un error técnico: {str(e)}"
        await context.bot.send_message(chat_id=chat_id, text=error_msg)
        print(f"Error detallado: {e}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    
    # AQUÍ ESTABA EL ERROR: Cambiamos 'echo' por 'handle_message'
    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    
    application.add_handler(start_handler)
    application.add_handler(message_handler)
    
    print("InsightFlow Bot está corriendo...")
    application.run_polling()

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    
    # Crear carpeta por usuario si no existe
    user_path = f"data/{update.effective_user.id}"
    os.makedirs(user_path, exist_ok=True)
    
    file_path = os.path.join(user_path, file_name)
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"Archivo '{file_name}' guardado con éxito. Ya puedes hacerme preguntas sobre él.")

# En la sección de handlers agregarías:
# application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
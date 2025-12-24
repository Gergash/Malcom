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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    document = update.message.document
    
    user_folder = os.path.join("data", str(chat_id))
    os.makedirs(user_folder, exist_ok=True)
    file_path = os.path.join(user_folder, document.file_name)
    
    # Descargar el archivo
    new_file = await context.bot.get_file(document.file_id)
    await new_file.download_to_drive(file_path)
    # ESTA LÍNEA ES CLAVE: Guardamos la ruta en la "memoria" del bot para este usuario
    context.user_data['current_file'] = file_path
    print(f"DEBUG: Archivo guardado exitosamente en: {file_path}") # Esto DEBE salir en tu terminal
    await update.message.reply_text(f"✅ Archivo '{document.file_name}' recibido. ¿Qué quieres saber sobre estos datos?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    file_path = context.user_data.get('current_file')
    print(f"--- NUEVA CONSULTA ---")
    print(f"Usuario {chat_id} dice: {user_text}")
    print(f"Archivo en memoria: {file_path}")
    # RECUPERAMOS la ruta del archivo guardado anteriormente
    file_path = context.user_data.get('current_file')
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Pasamos la ruta al agente (si no hay archivo, pasará None)
        respuesta_ia = await agent.analyze_data(user_text, file_path)
        
        await context.bot.send_message(chat_id=chat_id, text=respuesta_ia)
        
        # Si la IA creó una imagen, la enviamos
        if os.path.exists("output_plot.png"):
            await update.message.reply_photo(photo=open("output_plot.png", "rb"))
            os.remove("output_plot.png")
            
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")

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
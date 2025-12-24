import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from agents.analyst_agent import AnalystAgent
import asyncio

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
    
    # Recuperamos la ruta del archivo (limpiamos el código repetido)
    file_path = context.user_data.get('current_file')
    
    print(f"\n--- NUEVA CONSULTA ---")
    print(f"Usuario {chat_id} dice: {user_text}")
    print(f"Archivo en memoria: {file_path}")
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        # 1. Llamada al agente
        respuesta_ia = await agent.analyze_data(user_text, file_path)
        # 2. Enviamos el texto primero
        await context.bot.send_message(chat_id=chat_id, text=respuesta_ia)  
        # 3. Pequeña pausa de seguridad (0.5 seg) para que el sistema de archivos asiente la imagen
        # LOG DE DIAGNÓSTICO
        print(f"DEBUG: ¿Existe el archivo de imagen? {os.path.exists('output_plot.png')}")
        await asyncio.sleep(1)
        
        # 4. Verificación y envío de la imagen
        if os.path.exists("output_plot.png"):
            print("LOG: ¡Gráfica encontrada! Enviando a Telegram...")
            # Usamos 'async with' para un manejo de archivos más moderno
            with open("output_plot.png", "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id, 
                    photo=photo, 
                    caption="📊 Análisis visual generado por InsightFlow."
                )
            
            # Limpieza inmediata
            os.remove("output_plot.png")
        else:
            # Si el usuario pidió una gráfica y no está, lo registramos en consola
            if "grafic" in user_text.lower() or "dibuj" in user_text.lower():
                print("LOG: El usuario pidió gráfica pero 'output_plot.png' no fue creado.")
                
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
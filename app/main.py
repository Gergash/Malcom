import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from agents.analyst_agent import AnalystAgent
from agents.predictor_agent import PredictorAgent
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
predictor = PredictorAgent()

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
            )
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
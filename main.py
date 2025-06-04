"""
Bot de Telegram para administrar la automatización de pruebas de tarjetas.

Funciones:
- Recibe archivos y parámetros desde Telegram
- Guarda estructura y datos localmente
- Ejecuta flujo principal cada 5 minutos
- Informa al usuario el estado de cada tarjeta por ID
"""

import asyncio
import logging
import os
from datetime import datetime
import random
import string

from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.bot import procesar_tarjeta  
from core.result_saver import guardar_resultado
from core.reader import cargar_tarjetas, cargar_dummies

# ================================
# CONFIGURACIÓN
# ================================
TOKEN = "7425119793:AAHaqWPRf-22s6_t2BdG8VcK-7q7E7UQ-1U"  # ← Pega tu token de Telegram aquí
TIEMPO_ENTRE_INTENTOS = 300
MAXIMO_POR_HORA = 12
ESTRUCTURAS = ["structure/sec-1.txt", "structure/sec-2.txt", "structure/sec-3.txt"]

# ================================
# FUNCIONES AUXILIARES
# ================================

def generar_id_unico():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

def guardar_archivo(document: Document, folder: str):
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, document.file_name)
    return file_path

async def procesar_todo(context: ContextTypes.DEFAULT_TYPE, chat_id):
    tarjetas = cargar_tarjetas("data/TTCA.txt")
    dummies = cargar_dummies("data/dummies.txt")

    for i in range(min(MAXIMO_POR_HORA, len(tarjetas))):
        tarjeta = tarjetas[i]
        datos = dummies[i % len(dummies)]
        estructura_actual = ESTRUCTURAS[i % len(ESTRUCTURAS)]

        id_unico = generar_id_unico()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            mensaje = await procesar_tarjeta(tarjeta, datos, estructura_path=estructura_actual)
        except Exception as e:
            mensaje = f"[ERROR] {str(e)}"

        guardar_resultado({
            "id": id_unico,
            "tarjeta": tarjeta,
            "fecha": timestamp,
            "mensaje": mensaje
        })

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧾 ID: {id_unico}\n💳 Tarjeta terminada en ****{tarjeta[-4:]}\n📅 Fecha: {timestamp}\n📣 Resultado: {mensaje}"
        )

        if i < MAXIMO_POR_HORA - 1:
            await asyncio.sleep(TIEMPO_ENTRE_INTENTOS)

# ================================
# HANDLERS DE TELEGRAM
# ================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Envíame los archivos y escribe /probar para iniciar el análisis.")

async def recibir_archivos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    folder = "data" if "TTCA" in document.file_name or "dummies" in document.file_name else "structure"
    file_path = guardar_archivo(document, folder)
    await document.get_file().download_to_drive(file_path)
    await update.message.reply_text(f"📂 Archivo guardado en {folder}: {document.file_name}")

async def comando_probar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Iniciando pruebas de tarjetas...")
    await procesar_todo(context, update.message.chat_id)

async def estado_tarjeta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.result_saver import JSON_FILE
    import json

    if not context.args:
        await update.message.reply_text("❗ Uso correcto: /estado <ID>")
        return

    id_buscado = context.args[0].strip().upper()

    if not os.path.exists(JSON_FILE):
        await update.message.reply_text("⚠️ No hay registros aún.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        registros = json.load(f)

    for registro in registros:
        if registro["id"] == id_buscado:
            await update.message.reply_text(
                f"📌 Resultado ID {id_buscado}:\n💳 Tarjeta: ****{registro['tarjeta'][-4:]}\n🕐 Fecha: {registro['fecha']}\n📣 Estado: {registro['mensaje']}"
            )
            return

    await update.message.reply_text(f"❌ No se encontró el ID {id_buscado}.")

# ================================
# BOOTSTRAP
# ================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("probar", comando_probar))
    app.add_handler(CommandHandler("estado", estado_tarjeta))
    app.add_handler(MessageHandler(filters.Document.ALL, recibir_archivos))

    print("[BOT] Ejecutando...")
    app.run_polling()

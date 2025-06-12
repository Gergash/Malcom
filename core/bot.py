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
import json
from typing import Dict, Optional

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

def generar_id_unico(longitud=5):
    """Genera un ID único aleatorio de la longitud especificada"""
    caracteres = string.ascii_uppercase + string.digits
    return ''.join(random.choice(caracteres) for _ in range(longitud))

def parse_card_message(message: str) -> Optional[Dict]:
    """
    Parse a message containing card information in the format:
    Merchant|Plan|CardNumber|Month|Year|CVV|Type|Bank|CardName|Network|Country
    
    Returns None if the format is invalid
    """
    try:
        parts = message.strip().split('|')
        if len(parts) != 11:
            return None
            
        return {
            "merchant": parts[0],
            "plan": parts[1],
            "card_number": parts[2],
            "month": parts[3],
            "year": parts[4],
            "cvv": parts[5],
            "type": parts[6],
            "bank": parts[7],
            "card_name": parts[8],
            "network": parts[9],
            "country": parts[10]
        }
    except:
        return None

async def handle_card_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming messages that might contain card information and save them using result_saver
    """
    message = update.message.text
    card_info = parse_card_message(message)
    
    if card_info:
        # Generate unique ID and timestamp
        id_unico = generar_id_unico()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create data structure compatible with result_saver
        result_data = {
            "id": id_unico,
            "tarjeta": card_info["card_number"],
            "merchant": card_info["merchant"],
            "plan": card_info["plan"],
            "mes": card_info["month"],
            "año": card_info["year"],
            "cvv": card_info["cvv"],
            "tipo": card_info["type"],
            "banco": card_info["bank"],
            "nombre_tarjeta": card_info["card_name"],
            "red": card_info["network"],
            "pais": card_info["country"],
            "fecha": timestamp,
            "mensaje": f"Card received - {card_info['bank']} {card_info['type']} {card_info['network']}"
        }
        
        # Save using result_saver (this will save in CSV, JSON, and XLSX)
        guardar_resultado(result_data)
        
        # Send confirmation message
        await update.message.reply_text(
            f"✅ Card saved successfully!\n"
            f"📌 ID: {id_unico}\n"
            f"💳 Card: ****{card_info['card_number'][-4:]}\n"
            f"🏦 Bank: {card_info['bank']}\n"
            f"💰 Plan: {card_info['plan']}\n"
            f"🌐 Network: {card_info['network']}\n"
            f"🏷️ Type: {card_info['type']}\n"
            f"🗓️ Expiry: {card_info['month']}/{card_info['year']}\n"
            f"🌍 Country: {card_info['country']}\n"
            f"📅 Date: {timestamp}"
        )
    else:
        # Only reply if the message looks like it was trying to be a card but failed
        if '|' in message:
            await update.message.reply_text(
                "❌ Invalid card format. Please use:\n"
                "Merchant|Plan|CardNumber|Month|Year|CVV|Type|Bank|CardName|Network|Country"
            )

async def comando_probar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Iniciando pruebas de tarjetas...")
    await procesar_todo(context, update.message.chat_id)

async def estado_tarjeta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from core.result_saver import JSON_FILE
    
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
                f"📌 Resultado ID {id_buscado}:\n"
                f"💳 Tarjeta: ****{registro['tarjeta'][-4:]}\n"
                f"🕐 Fecha: {registro['fecha']}\n"
                f"📣 Estado: {registro['mensaje']}"
            )
            return

    await update.message.reply_text(f"❌ No se encontró el ID {id_buscado}.")

def main():
    """
    Función principal que inicia el bot
    """
    # Configurar logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # Crear la aplicación
    application = Application.builder().token(TOKEN).build()

    # Agregar manejadores de comandos
    application.add_handler(CommandHandler("probar", comando_probar))
    application.add_handler(CommandHandler("estado", estado_tarjeta))
    
    # Agregar manejador para mensajes de tarjetas
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_card_message))

    # Iniciar el bot
    application.run_polling()

if __name__ == "__main__":
    main()

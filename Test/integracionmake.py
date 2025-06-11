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

import google.generativeai as genai
import pandas as pd
import os
import matplotlib.pyplot as plt
import re
from dotenv import load_dotenv

load_dotenv()

# 1. Configuración de la API con el nombre exacto de tu lista
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class AnalystAgent:
    def __init__(self):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # Definimos la identidad fija AQUÍ
        self.identity = (
            "Eres el cerebro analítico de InsightFlow, una plataforma de BI avanzada.\n"
            "Tu propósito es transformar datos complejos en insights de negocio claros.\n"
            "Siempre te presentas como el Analista Senior de InsightFlow.\n"
            "Cuando hay archivos, generas código Python local para analizarlos."
        )
        # Configuramos el modelo con la instrucción de sistema permanente
        self.model = genai.GenerativeModel(
            model_name='models/gemini-2.5-flash',
            system_instruction=self.identity # <-- Esto fija su propósito
        )

    def _extraer_codigo(self, texto_ia):
        """Extrae el bloque de código Python de la respuesta de la IA."""
        patron = r"```python\s*(.*?)\s*```"
        match = re.search(patron, texto_ia, re.DOTALL)
        if match:
            return match.group(1)
        return texto_ia.replace("```python", "").replace("```", "").strip()

    async def analyze_data(self, user_query: str, local_file_path: str = None):
        if not local_file_path or not os.path.exists(local_file_path):
            response = self.model.generate_content(user_query)
            return response.text

        # 2. PROCESAMIENTO DE ESQUEMA (Evita el Error 400 de tokens)
        try:
            # Leemos solo la estructura para no saturar la ventana de contexto
            df_sample = pd.read_csv(local_file_path, nrows=2)
            schema_info = (
                f"Columnas detectadas: {list(df_sample.columns)}\n"
                f"Muestra de datos:\n{df_sample.to_dict('records')}"
            )
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        # 3. SYSTEM PROMPT (IA como Arquitecto, tu PC como Obrero)
        clean_path = local_file_path.replace("\\", "/")
        system_prompt = (
            "Eres el cerebro analítico de InsightFlow basado en Gemini 2.5 Pro.\n"
            "TU OBJETIVO: Generar código Python para analizar archivos locales masivos.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi sistema lo lea.\n"
            f"2. Usa la ruta exacta del archivo: '{clean_path}'\n"
            "3. IMPORTANTE: Si se pide una gráfica, usa matplotlib y guarda SIEMPRE como 'output_plot.png'.\n"
            "4. Usa 'plt.savefig(\"output_plot.png\")' y luego 'plt.close()'.\n"
            "5. Responde con un análisis profesional y el código dentro de un bloque ```python."
        )

        prompt = f"{system_prompt}\n\nESTRUCTURA DEL ARCHIVO:\n{schema_info}\n\nPREGUNTA DEL USUARIO: {user_query}"

        # 4. GENERACIÓN DE CÓDIGO
        try:
            response = self.model.generate_content(prompt)
            respuesta_texto = response.text
            codigo_python = self._extraer_codigo(respuesta_texto)
        except Exception as e:
            return f"Error de comunicación con Gemini 2.5 Pro: {str(e)}"

        # 5. EJECUCIÓN LOCAL (Potencia ilimitada para tus 10GB)
        try:
            # Entorno de ejecución local
            namespace = {'pd': pd, 'plt': plt, 'os': os}
            print(f"DEBUG: Ejecutando análisis local con Gemini 2.5 Pro sobre {clean_path}...")
            
            # El código corre en tu máquina, no en los servidores de Google
            exec(codigo_python, namespace)
            
            return respuesta_texto
        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            return f"Error en ejecución local: {e}\n\nCódigo generado: {codigo_python}"
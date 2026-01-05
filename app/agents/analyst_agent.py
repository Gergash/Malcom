import google.generativeai as genai
import pandas as pd
import os
import matplotlib.pyplot as plt
import re
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# 1. Configuración global (Asegura que el SDK use la API Key)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class AnalystAgent:
    def __init__(self):
        # 2. Nombre del modelo corregido para evitar el Error 404
        # 'gemini-1.5-flash' es el identificador estándar más compatible
        self.model = genai.GenerativeModel('models/gemini-2.5-pro')

    def _extraer_codigo(self, texto_ia):
        """Extrae el bloque de código Python de la respuesta de la IA."""
        patron = r"```python\s*(.*?)\s*```"
        match = re.search(patron, texto_ia, re.DOTALL)
        if match:
            return match.group(1)
        # Limpieza manual si no hay etiquetas de bloque ```python
        return texto_ia.replace("```python", "").replace("```", "").strip()

    async def analyze_data(self, user_query: str, local_file_path: str = None):
        # Si no hay archivo, respuesta de texto simple
        if not local_file_path or not os.path.exists(local_file_path):
            response = self.model.generate_content(user_query)
            return response.text

        # 3. PROCESAMIENTO LOCAL DEL ESQUEMA (Evita el Error 400 de Tokens)
        try:
            # Leemos solo 2 filas para enviar solo la estructura a la IA
            df_sample = pd.read_csv(local_file_path, nrows=2)
            schema_info = (
                f"Columnas detectadas: {list(df_sample.columns)}\n"
                f"Ejemplo de datos:\n{df_sample.to_dict('records')}"
            )
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        # 4. SYSTEM PROMPT (IA como Arquitecto, tu PC como Obrero)
        # Convertimos la ruta a formato compatible (barras /) para evitar errores en Windows
        clean_path = local_file_path.replace("\\", "/")
        
        system_prompt = (
            "Eres el motor de análisis de InsightFlow.\n"
            "TU OBJETIVO: Generar código Python para analizar un archivo local masivo.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi PC lo lea.\n"
            f"2. Usa la ruta exacta del archivo: '{clean_path}'\n"
            "3. IMPORTANTE: Si se pide una gráfica, usa matplotlib y guarda SIEMPRE como 'output_plot.png'.\n"
            "4. Usa 'plt.savefig(\"output_plot.png\")' y luego 'plt.close()'.\n"
            "5. Responde con una breve explicación del análisis y el código dentro de un bloque ```python."
        )

        prompt = f"{system_prompt}\n\nESTRUCTURA DEL ARCHIVO:\n{schema_info}\n\nPREGUNTA DEL USUARIO: {user_query}"

        # 5. LLAMADA A LA IA
        try:
            # Enviamos un prompt ligero (Esquema + Pregunta)
            response = self.model.generate_content(prompt)
            respuesta_texto = response.text
            codigo_python = self._extraer_codigo(respuesta_texto)
        except Exception as e:
            return f"Error en la comunicación con Gemini: {str(e)}"

        # 6. EJECUCIÓN LOCAL (Aquí ocurre la magia de procesar 50k filas o 10GB)
        try:
            # Definimos el entorno de ejecución (Namespace)
            namespace = {'pd': pd, 'plt': plt, 'os': os}
            
            print(f"DEBUG: Ejecutando análisis local sobre {clean_path}...")
            
            # El código de la IA se ejecuta en TU procesador y TU RAM
            exec(codigo_python, namespace)
            
            # Retornamos la explicación de la IA (el archivo .png ya se creó localmente)
            return respuesta_texto

        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            return f"La IA sugirió un análisis, pero hubo un error al ejecutarlo localmente: {e}\n\nCódigo intentado:\n{codigo_python}"
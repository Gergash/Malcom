import google.generativeai as genai
import os
import pandas as pd
import matplotlib.pyplot as plt
import re
from dotenv import load_dotenv

load_dotenv()

# Configuración global de la API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class AnalystAgent:
    def __init__(self):
        # Usamos gemini-1.5-flash: es el más estable y rápido para análisis de datos
        # No usamos el prefijo 'models/' ni 'gemini-2.5' para evitar errores 404
        self.model = genai.GenerativeModel(model_name='gemini-1.5-flash')

    def _extraer_codigo(self, texto_ia):
        """Limpia la respuesta de la IA para obtener solo el código ejecutable."""
        patron = r"```python\s*(.*?)\s*```"
        match = re.search(patron, texto_ia, re.DOTALL)
        if match:
            return match.group(1)
        return texto_ia.replace("```python", "").replace("```", "").strip()

    async def analyze_data(self, user_query: str, local_file_path: str = None):
        # Si no hay archivo, respondemos como un chat normal
        if not local_file_path or not os.path.exists(local_file_path):
            response = self.model.generate_content(user_query)
            return response.text

        # 1. PREPARACIÓN DEL ESQUEMA (Gasta menos de 500 tokens, sin importar el tamaño del CSV)
        try:
            # Leemos solo 2 filas para darle a la IA la estructura de las columnas
            df_sample = pd.read_csv(local_file_path, nrows=2)
            schema_info = (
                f"ESTRUCTURA DEL ARCHIVO LOCAL:\n"
                f"Columnas: {list(df_sample.columns)}\n"
                f"Ejemplo de datos:\n{df_sample.to_dict('records')}"
            )
        except Exception as e:
            return f"Error al leer el esquema del archivo local: {e}"

        # 2. SYSTEM PROMPT (IA como Arquitecto, tu PC como Obrero)
        clean_path = local_file_path.replace("\\", "/")
        system_prompt = (
            "Eres el motor de InsightFlow. El usuario ha subido un archivo masivo.\n"
            "REGLA DE ORO: El archivo es demasiado grande para enviarlo por chat. "
            "Genera CÓDIGO PYTHON para que YO lo ejecute localmente en mi servidor.\n\n"
            f"RUTA DEL ARCHIVO: '{clean_path}'\n"
            "INSTRUCCIONES TÉCNICAS:\n"
            "1. Usa pandas para leer el archivo desde la ruta proporcionada.\n"
            "2. Si se pide una gráfica, usa matplotlib y guárdala SIEMPRE como 'output_plot.png'.\n"
            "3. Usa plt.savefig('output_plot.png') y luego plt.close() para liberar memoria.\n"
            "4. Devuelve el código dentro de bloques de triple comilla ```python."
        )

        prompt_parts = [
            system_prompt,
            f"\nINFORMACIÓN DEL ARCHIVO:\n{schema_info}",
            f"\nCONSULTA DEL USUARIO: {user_query}"
        ]

        # 3. LLAMADA A LA IA PARA GENERAR EL CÓDIGO
        try:
            # Enviamos solo el ESQUEMA (esto soluciona el error de tokens 400)
            response = self.model.generate_content(prompt_parts)
            respuesta_texto = response.text
            codigo_python = self._extraer_codigo(respuesta_texto)
        except Exception as e:
            return f"Error técnico en la comunicación (Tokens): {str(e)}"

        # 4. EJECUCIÓN LOCAL (Aquí es donde procesas 50k filas o 10GB sin límites de Google)
        try:
            # Entorno de ejecución local controlado
            namespace = {'pd': pd, 'plt': plt, 'os': os}
            
            print(f"DEBUG: Ejecutando análisis local sobre: {clean_path}")
            
            # Ejecución real en tu máquina
            exec(codigo_python, namespace)
            
            # Devolvemos la explicación que dio la IA
            return respuesta_texto

        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            return f"La IA sugirió un análisis, pero hubo un error al ejecutarlo localmente: {e}\n\nCódigo intentado:\n{codigo_python}"
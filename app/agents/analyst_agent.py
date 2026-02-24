import google.generativeai as genai
import pandas as pd
import os
import matplotlib.pyplot as plt
import re
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Extensiones que el analista puede usar (carpeta del usuario)
_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _get_latest_data_file_in_folder(user_data_folder: str):
    """Devuelve la ruta del archivo más reciente (CSV/XLSX) en la carpeta del usuario."""
    if not user_data_folder or not os.path.isdir(user_data_folder):
        return None
    candidates = []
    for name in os.listdir(user_data_folder):
        if name.lower().endswith(_DATA_EXTENSIONS):
            path = os.path.join(user_data_folder, name)
            try:
                candidates.append((os.path.getmtime(path), path))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _read_schema_sample(path: str):
    """Lee una muestra (2 filas) para obtener esquema; soporta CSV y Excel."""
    path_lower = path.lower()
    if path_lower.endswith(".csv"):
        return pd.read_csv(path, nrows=2)
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, nrows=2)
    return pd.read_csv(path, nrows=2)


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

    async def analyze_data(
        self,
        user_query: str,
        local_file_path: str = None,
        user_data_folder: str = None,
    ):
        """
        Analiza según la pregunta del usuario.
        - local_file_path: archivo que acaba de subir (opcional).
        - user_data_folder: carpeta del usuario (data/{chat_id}); si no hay archivo,
          se usa el archivo de datos más reciente en esta carpeta.
        """
        # Resolver archivo: el enviado ahora o el más reciente en la carpeta del usuario
        file_path = local_file_path
        if not file_path and user_data_folder:
            file_path = _get_latest_data_file_in_folder(user_data_folder)
        if not file_path or not os.path.exists(file_path):
            response = self.model.generate_content(user_query)
            return response.text

        # PROCESAMIENTO DE ESQUEMA (evita saturar contexto)
        try:
            df_sample = _read_schema_sample(file_path)
            schema_info = (
                f"Columnas detectadas: {list(df_sample.columns)}\n"
                f"Muestra de datos:\n{df_sample.to_dict('records')}"
            )
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        clean_path = file_path.replace("\\", "/")
        # Indicar cómo leer según extensión (CSV vs Excel)
        path_lower = clean_path.lower()
        if path_lower.endswith((".xlsx", ".xls")):
            read_instruction = f"Usa pd.read_excel('{clean_path}') para cargar el archivo."
        else:
            read_instruction = f"Usa pd.read_csv('{clean_path}') para cargar el archivo."
        system_prompt = (
            "Eres el cerebro analítico de InsightFlow basado en Gemini 2.5 Pro.\n"
            "TU OBJETIVO: Generar código Python para analizar archivos locales masivos.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi sistema lo lea.\n"
            f"2. Ruta exacta del archivo: '{clean_path}'. {read_instruction}\n"
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
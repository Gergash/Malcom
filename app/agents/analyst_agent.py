import google.generativeai as genai
import os
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# Configurar la API con la librería estable
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

#LISTA LOS MODELOS DISPONIBLES PARA UTILIZAR
#for m in genai.list_models():
#    if 'generateContent' in m.supported_generation_methods:
#        print(m.name)

class AnalystAgent:
    def __init__(self):
        # Usamos 1.5-flash que es extremadamente estable con esta librería
        self.model = genai.GenerativeModel(
            model_name='models/gemini-2.5-flash',
            tools=[{'code_execution': {}}] # El MCP para Python
        )
    async def analyze_data(self, user_query: str, local_file_path: str = None):
        # 1. System Prompt Reforzado
        system_prompt = (
            "Eres un Analista Senior de InsightFlow. El usuario ha subido un archivo extenso.\n"
            "REGLA DE ORO: No intentes leer los datos del prompt. USA la herramienta 'code_execution'.\n"
            "He cargado el archivo en tu entorno. Usa pandas para analizarlo completamente.\n"
            "Si se piden gráficas, guárdalas como 'output_plot.png'."
        )
        prompt_parts = [system_prompt]

        if local_file_path and os.path.exists(local_file_path):
            try:
                # 2. ESQUEMA (Gasta poquísimos tokens)
                df_sample = pd.read_csv(local_file_path, nrows=2)
                schema_info = f"\nEstructura: {list(df_sample.columns)}\nMuestra: {df_sample.to_dict('records')}"
                prompt_parts.append(schema_info)

                # 3. CORRECCIÓN DEL MIME TYPE (Aquí se soluciona el Error 400)
                file_ext = local_file_path.lower()
                if file_ext.endswith('.csv'):
                    mime_type = 'text/csv' # Forzamos el tipo correcto para Google
                elif file_ext.endswith('.xlsx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                else:
                    mime_type = 'text/plain'

                # Subida a la API de Archivos (Soporta hasta 2GB)
                remote_file = genai.upload_file(path=local_file_path, mime_type=mime_type)
                print(f"DEBUG: Archivo subido exitosamente como {mime_type}: {remote_file.name}")
                prompt_parts.append(remote_file)

            except Exception as e:
                print(f"Error procesando archivo: {e}")
                return f"Tuve un problema al leer el archivo: {str(e)}"

        # 4. Consulta del usuario
        prompt_parts.append(f"Consulta: {user_query}")

        # 5. Respuesta y captura de imagen
        try:
            response = self.model.generate_content(prompt_parts)
            full_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text: full_text += part.text
                    if part.inline_data and part.inline_data.mime_type == 'image/png':
                        with open("output_plot.png", "wb") as f:
                            f.write(part.inline_data.data)
                return full_text if full_text else "Análisis completado."
        except Exception as e:
            return f"Error técnico en la comunicación: {str(e)}"
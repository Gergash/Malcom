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
        # 1. Definición del comportamiento (System Prompt) optimizado para grandes datos
        system_prompt = (
            "Eres un Analista de Datos senior de InsightFlow.\n"
            "REGLAS DE ORO PARA GRANDES VOLÚMENES:\n"
            "1. Se te proporcionará un ESQUEMA (columnas y muestra) del archivo.\n"
            "2. Para responder, DEBES usar la herramienta de ejecución de código Python.\n"
            "3. No intentes 'leer' los datos como texto; usa pandas para procesar el archivo completo.\n"
            "4. Si se piden gráficas, guárdalas SIEMPRE como 'output_plot.png' usando plt.savefig().\n"
            "5. El archivo está disponible en el entorno de ejecución con el nombre que se te indique."
        )

        # 2. INICIALIZAMOS la lista de partes
        prompt_parts = [system_prompt]

        # 3. EXTRACCIÓN DE ESQUEMA (Para evitar el error de límite de tokens)
        if local_file_path and os.path.exists(local_file_path):
            print(f"IA: Analizando esquema de {local_file_path}...")
            try:
                # Leemos solo las primeras 5 filas para enviarle a la IA la estructura
                df_sample = pd.read_csv(local_file_path, nrows=5)
                
                schema_info = (
                    f"\n--- INFORMACIÓN DEL ARCHIVO ---\n"
                    f"Nombre: {os.path.basename(local_file_path)}\n"
                    f"Columnas detectadas: {list(df_sample.columns)}\n"
                    f"Tipos de datos: \n{df_sample.dtypes.to_string()}\n"
                    f"Muestra de las primeras filas:\n{df_sample.to_string()}\n"
                    f"--------------------------------"
                )
                prompt_parts.append(schema_info)

                # Subida a la API (Gemini File API permite hasta 2GB por archivo)
                # Al subirlo aquí, el modelo puede usarlo con 'code_execution'
                mime_type = 'text/csv'
                if local_file_path.endswith('.xlsx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                
                remote_file = genai.upload_file(path=local_file_path, mime_type=mime_type)
                print(f"IA: Archivo subido con éxito a la nube: {remote_file.name}")
                prompt_parts.append(remote_file)

            except Exception as e:
                print(f"IA: Error procesando esquema/subida: {e}")
        else:
            print("IA: No se encontró archivo local. Procesando solo texto.")

        # 4. AGREGAMOS la consulta del usuario
        prompt_parts.append(f"\nConsulta del usuario: {str(user_query)}")

        # 5. EJECUCIÓN Y RESPUESTA
        try:
            # Llamada al modelo (Ahora el prompt es pequeño, solo contiene el esquema y el link al archivo)
            response = self.model.generate_content(prompt_parts)

            full_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        full_text += part.text
                    
                    # Captura de la imagen generada por el código Python
                    if part.inline_data and part.inline_data.mime_type == 'image/png':
                        print("LOG: Detectada gráfica generada. Guardando localmente...")
                        with open("output_plot.png", "wb") as f:
                            f.write(part.inline_data.data)
                
                return full_text if full_text else "Análisis completado."
            
            return "No se generó contenido en la respuesta."

        except Exception as e:
            print(f"Error crítico: {e}")
            try:
                return response.text
            except:
                return f"Error técnico en InsightFlow: {str(e)}"
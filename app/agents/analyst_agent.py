import google.generativeai as genai
import os
from dotenv import load_dotenv

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
        # 1. Definimos el comportamiento (System Prompt)
        system_prompt = (
            "Eres un Analista de Datos experto de InsightFlow.\n"
            "TIENES ACTIVADA LA HERRAMIENTA DE EJECUCIÓN DE CÓDIGO PYTHON.\n"
            "INSTRUCCIONES OBLIGATORIAS:\n"
            "1. Si el usuario pide gráficas, DEBES escribir y EJECUTAR un bloque de código Python.\n"
            "2. Usa pandas para leer el archivo. El archivo se carga como un objeto de tipo 'File'.\n"
            "3. Guarda la gráfica con: plt.savefig('output_plot.png')\n"
            "4. No des solo el código, ejecútalo y entrega el análisis."
        )
        # 2. INICIALIZAMOS la lista PRIMERO
        prompt_parts = [system_prompt]
        # 3. MANEJO DE ARCHIVOS (Subida y asociación)
        if local_file_path and os.path.exists(local_file_path):
            print(f"IA: Detectado archivo en {local_file_path}. Subiendo...")
            try:
                mime_type = 'text/csv'
                if local_file_path.endswith('.xlsx'):
                    mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            
                # Subida a la API
                remote_file = genai.upload_file(path=local_file_path, mime_type=mime_type)
                print(f"IA: Archivo subido con éxito: {remote_file.name}")
            
                # Agregamos el archivo a la lista de partes
                prompt_parts.append(remote_file)
            
                # Le damos una pista a la IA sobre cómo leer el archivo en su entorno
                prompt_parts.append(f"Nota: El archivo de datos es {os.path.basename(local_file_path)}.")
            
            except Exception as e:
                print(f"IA: Error crítico en subida: {e}")
        else:
            print("IA: No se encontró archivo local. Procesando solo texto.")

        # 4. AGREGAMOS la consulta del usuario al FINAL
        prompt_parts.append(f"Consulta del usuario: {str(user_query)}")
        # 5. EJECUCIÓN Y RESPUESTA (Actualizado para capturar imágenes)
        try:
            # Enviamos todas las piezas juntas en orden (Instrucciones + Archivo + Consulta)
            response = self.model.generate_content(prompt_parts)

            full_text = ""
            # Recorremos las partes de la respuesta para buscar texto y datos binarios
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    # 1. Extraer texto si existe
                    if part.text:
                        full_text += part.text
                    
                    # 2. Extraer imagen si la herramienta Code Execution la generó
                    # Verificamos inline_data para capturar el gráfico directamente de la respuesta
                    if part.inline_data and part.inline_data.mime_type == 'image/png':
                        print("LOG: Detectada imagen binaria en la respuesta de Gemini. Guardando...")
                        with open("output_plot.png", "wb") as f:
                            f.write(part.inline_data.data)
                
                return full_text if full_text else "Análisis completado (sin resumen de texto)."
            
            return "Procesado, pero no se generó contenido en la respuesta."

        except Exception as e:
            print(f"Error crítico procesando la respuesta de la IA: {e}")
            # Intentamos retornar al menos el texto plano si el bucle falla
            try:
                return response.text
            except:
                return f"Error técnico en la comunicación con la IA: {str(e)}"
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
        # Preparar lista de archivos para que la IA sepa dónde están
        prompt_parts = [user_query]  
        if local_file_path and os.path.exists(local_file_path):
            # LOG DE CONSOLA 2
            print(f"IA: Detectado archivo en {local_file_path}. Subiendo a Google API...")
        try:
            # FORZAMOS el mime_type a 'text/csv' para evitar el error 400
            # Si es un Excel real (.xlsx), usa 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            mime_type = 'text/csv' 
            if local_file_path.endswith('.xlsx'):
                mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif local_file_path.endswith('.pdf'):
                mime_type = 'application/pdf'

            remote_file = genai.upload_file(path=local_file_path, mime_type=mime_type)
            print(f"IA: Archivo subido con éxito: {remote_file.name}")
            prompt_parts.append(remote_file)
            # Instrucción explícita para activar el código Python
            prompt_parts.append(
                "\nINSTRUCCIÓN TÉCNICA: Tienes este archivo adjunto. "
                "Cárgalo usando la librería pandas en Python, analiza los datos para responder la duda "
                "y genera una gráfica con matplotlib guardándola como 'output_plot.png'."
            )
        except Exception as e:
            print(f"IA: Error en subida: {e}")

        response = self.model.generate_content(prompt_parts)
        try:
            # Recorremos las partes de la respuesta y unimos solo las que tienen texto
            full_text = "".join([part.text for part in response.candidates[0].content.parts if part.text])
            return full_text
        except Exception as e:
            print(f"Error extrayendo texto: {e}")
        # Si falla el anterior, intentamos la forma directa pero protegida
        return response.text if response.text else "He procesado los datos, pero no pude generar un resumen de texto."
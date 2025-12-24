import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configurar la API con la librería estable
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class AnalystAgent:
    def __init__(self):
        # Usamos 1.5-flash que es extremadamente estable con esta librería
        self.model = genai.GenerativeModel(
            model_name='models/gemini-1.5-flash',
            tools=[{'code_execution': {}}] # El MCP para Python
        )

    async def analyze_data(self, user_query: str, file_paths: list = None):
        # Preparar lista de archivos para que la IA sepa dónde están
        context_files = ""
        if file_paths:
            context_files = "\nArchivos del cliente en el servidor:\n" + "\n".join(file_paths)

        prompt = f"""
        Eres el analista de 'InsightFlow'. 
        Pregunta: {user_query}
        {context_files}
        
        Instrucciones:
        1. Usa Python para analizar datos o crear gráficas si es necesario.
        2. Guarda cualquier gráfica como 'output_plot.png'.
        3. Responde siempre con insights para mejorar comunidades digitales.
        """
        
        response = self.model.generate_content(prompt)
        return response.text
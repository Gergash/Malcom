import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configuración de la API de Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class AnalystAgent:
    def __init__(self):
        # Usamos 1.5-flash por su rapidez y bajo costo para el MVP
        # El 'code_execution' es el "MCP" que permite a Gemini correr Python
        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            tools=[{'code_execution': {}}]
        )

    async def analyze_data(self, user_query: str, file_paths: list = None):
        """
        Recibe la pregunta del usuario y una lista de rutas de archivos locales.
        """
        
        # Construimos el contexto de los archivos si existen
        context_files = ""
        if file_paths:
            context_files = "\nArchivos disponibles para el análisis:\n" + "\n".join(file_paths)

        prompt = f"""
        Eres el cerebro analítico de 'InsightFlow', una plataforma de creación de comunidades y estrategia digital.
        Tu objetivo es generar insights accionables.
        
        Contexto del usuario: {user_query}
        {context_files}
        
        Instrucciones:
        1. Si el usuario pide una gráfica o tendencia, escribe código Python para leer los archivos, 
           crea la gráfica con matplotlib y guárdala SIEMPRE como 'output_plot.png'.
        2. Si el usuario hace una pregunta sobre el contenido de los documentos (PDF/TXT), analiza el texto.
        3. Siempre termina con un insight estratégico para el negocio (ej: 'Tus menciones subieron un 20%, deberías publicar más a las 6 PM').
        
        Responde de forma profesional y clara.
        """

        # Generar contenido
        response = self.model.generate_content(prompt)
        
        return response.text
import io
import contextlib
import google.generativeai as genai
import pandas as pd
import os
import matplotlib.pyplot as plt
import re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Extensiones que el analista puede usar (carpeta del usuario)
_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")

# Límite de Telegram: 4096 caracteres por mensaje. Dejamos margen de 30.
MAX_RESPONSE_CHARS = 4096 - 30  # 4066
LENGTH_INSTRUCTION = (
    f"LÍMITE ESTRICTO: tu respuesta debe tener MÁXIMO {MAX_RESPONSE_CHARS} caracteres (límite del canal). "
    "Redacta de forma concisa: prioriza hallazgos clave, evita listas interminables y repeticiones. "
    "Si el análisis es extenso, resume en secciones breves con los números y conclusiones más importantes."
)


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
    """
    Lee una muestra (2 filas) para obtener esquema; soporta CSV y Excel.
    Para CSV prueba UTF-8, luego latin-1/cp1252 si falla (evita error 'utf-8 codec can't decode').
    Devuelve (DataFrame, encoding_usado o None para Excel).
    """
    path_lower = path.lower()
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, nrows=2), None
    # CSV: intentar varios encodings
    for encoding in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            df = pd.read_csv(path, nrows=2, encoding=encoding)
            return df, encoding
        except (UnicodeDecodeError, Exception):
            continue
    return pd.read_csv(path, nrows=2, encoding="latin-1"), "latin-1"


class AnalystAgent:
    def __init__(self, knowledge_agent=None):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.knowledge_agent = knowledge_agent  # opcional: búsqueda semántica en documentos
        # Definimos la identidad fija AQUÍ
        self.identity = (
            "Eres el cerebro analítico de InsightFlow, una plataforma de BI avanzada.\n"
            "Tu propósito es transformar datos complejos en insights de negocio claros.\n"
            "Siempre te presentas como el Analista Senior de InsightFlow.\n"
            "Cuando hay archivos, generas código Python local para analizarlos.\n"
            f"Siempre que des una respuesta en texto, respétala máximo {MAX_RESPONSE_CHARS} caracteres (límite del canal): sé conciso, prioriza hallazgos clave."
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

    def _sanitize_code_for_exec(self, codigo: str) -> str:
        """
        Evita que caracteres como ¡ (U+00A1) o ¿ (U+00BF) en la salida de la IA
        rompan exec() (invalid character en línea 1).
        """
        if not codigo:
            return codigo
        # Quitar BOM y espacios/caracteres raros al inicio
        codigo = codigo.lstrip("\ufeff\u00a0")
        # Reemplazar ¡ y ¿ que pueden aparecer al inicio de línea o en comentarios
        codigo = codigo.replace("\u00a1", "# ")   # ¡
        codigo = codigo.replace("\u00bf", "# ")   # ¿
        return codigo

    def _cap_response_length(self, text: str) -> str:
        """Asegura que la respuesta no supere el límite del mensaje (Telegram)."""
        if not text or len(text) <= MAX_RESPONSE_CHARS:
            return text or ""
        return text[: MAX_RESPONSE_CHARS - 50].rstrip() + "\n\n[— Respuesta recortada por límite del mensaje.]"

    def _looks_like_python_code(self, codigo: str) -> bool:
        """
        Detecta si el bloque extraído es código Python ejecutable y no prosa con #.
        Si la IA respondió con texto en lugar de código (ej. saludo o explicación),
        no debemos ejecutarlo.
        """
        if not codigo or not codigo.strip():
            return False
        codigo = codigo.strip()
        # Debe contener indicios de código de análisis (pandas/archivo)
        has_pandas_or_io = (
            "read_csv" in codigo or "read_excel" in codigo
            or "pd." in codigo or "import pandas" in codigo or "import pd" in codigo
        )
        # Debe tener al menos una línea que no sea solo comentario
        non_comment = [l for l in codigo.splitlines() if l.strip() and not l.strip().startswith("#")]
        return bool(has_pandas_or_io and len(non_comment) >= 1)

    def _get_document_context(self, user_query: str, top_k: int = 5) -> str:
        """
        Búsqueda semántica en la base vectorial de documentos (PDF, DOCX, TXT).
        Si no hay knowledge_agent o no hay resultados, devuelve cadena vacía.
        """
        if not self.knowledge_agent:
            return ""
        try:
            results = self.knowledge_agent.search(user_query, top_k=top_k)
            if not results:
                return ""
            lines = []
            for r in results:
                source = r.get("source", "documento")
                text = (r.get("text", "") or "").strip()
                if text:
                    lines.append(f"[Fuente: {source}]\n{text}")
            if not lines:
                return ""
            return "CONTEXTO DE DOCUMENTOS INDEXADOS (reportes, reglas de negocio, etc.):\n\n" + "\n\n---\n\n".join(lines)
        except Exception as e:
            print(f"DEBUG: búsqueda semántica fallida: {e}")
            return ""

    async def analyze_data(
        self,
        user_query: str,
        local_file_path: str = None,
        user_data_folder: str = None,
        chat_id: int = None,
    ):
        """
        Analiza según la pregunta del usuario.
        - local_file_path: archivo que acaba de subir (opcional).
        - user_data_folder: carpeta del usuario (data/{chat_id}); si no hay archivo,
          se usa el archivo de datos más reciente en esta carpeta.
        Antes de responder, hace búsqueda semántica en la base vectorial (si hay
        KnowledgeAgent) para complementar con documentos de negocio (PDF, DOCX, TXT).
        """
        # Búsqueda semántica en documentos indexados (ej. "junio", "cierre planta")
        document_context = self._get_document_context(user_query)

        # Resolver archivo: el enviado ahora o el más reciente en la carpeta del usuario
        file_path = local_file_path
        if not file_path and user_data_folder:
            file_path = _get_latest_data_file_in_folder(user_data_folder)
        if not file_path or not os.path.exists(file_path):
            if document_context:
                response = self.model.generate_content(
                    f"{document_context}\n\nPREGUNTA DEL USUARIO: {user_query}\n\n"
                    "Responde como Analista Senior de InsightFlow, integrando si aplica la información de los documentos anteriores. "
                    + LENGTH_INSTRUCTION
                )
                return self._cap_response_length(response.text)
            response = self.model.generate_content(user_query + "\n\n" + LENGTH_INSTRUCTION)
            return self._cap_response_length(response.text)

        # PROCESAMIENTO DE ESQUEMA (evita saturar contexto; soporta encodings no UTF-8)
        try:
            df_sample, csv_encoding = _read_schema_sample(file_path)
            schema_info = (
                f"Columnas detectadas: {list(df_sample.columns)}\n"
                f"Muestra de datos:\n{df_sample.to_dict('records')}"
            )
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        clean_path = file_path.replace("\\", "/")
        # Indicar cómo leer según extensión (CSV vs Excel) y encoding si aplica
        path_lower = clean_path.lower()
        if path_lower.endswith((".xlsx", ".xls")):
            read_instruction = f"Usa pd.read_excel('{clean_path}') para cargar el archivo."
        else:
            if csv_encoding and csv_encoding != "utf-8":
                read_instruction = f"Usa pd.read_csv('{clean_path}', encoding='{csv_encoding}') para cargar el archivo (este CSV no es UTF-8)."
            else:
                read_instruction = f"Usa pd.read_csv('{clean_path}') para cargar el archivo."
        plot_filename = f"output_plot_{chat_id}.png" if chat_id else "output_plot.png"
        system_prompt = (
            "Eres el cerebro analítico de InsightFlow basado en Gemini 2.5 Pro.\n"
            "TU OBJETIVO: Generar código Python para analizar archivos locales masivos.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi sistema lo lea.\n"
            f"2. Ruta exacta del archivo: '{clean_path}'. {read_instruction}\n"
            f"3. IMPORTANTE: Si se pide una gráfica, usa matplotlib y guarda SIEMPRE como '{plot_filename}'.\n"
            f"4. Usa 'plt.savefig(\"{plot_filename}\")' y luego 'plt.close()'.\n"
            "5. IMPORTANTE: Imprime con print() todos los números, años y resultados clave del análisis para que el usuario los reciba.\n"
            "6. Responde con un análisis profesional y el código dentro de un bloque ```python.\n"
            "7. Si el usuario solo saluda o dice que va a subir un archivo (sin pedir análisis), responde en lenguaje natural SIN bloques de código."
        )

        doc_block = f"\n\n{document_context}\n\n" if document_context else ""
        prompt = f"{system_prompt}\n\nESTRUCTURA DEL ARCHIVO:\n{schema_info}{doc_block}PREGUNTA DEL USUARIO: {user_query}"

        # 4. GENERACIÓN DE CÓDIGO
        try:
            response = self.model.generate_content(prompt)
            respuesta_texto = response.text
            codigo_python = self._extraer_codigo(respuesta_texto)
            codigo_python = self._sanitize_code_for_exec(codigo_python)
        except Exception as e:
            return f"Error de comunicación con Gemini 2.5 Pro: {str(e)}"

        # 4b. Si la IA respondió con prosa (saludo, explicación) y no con código ejecutable, devolver la respuesta sin ejecutar
        if not self._looks_like_python_code(codigo_python):
            return self._cap_response_length(respuesta_texto)

        # 5. EJECUCIÓN LOCAL Y CAPTURA DE RESULTADOS
        try:
            output_capturado = io.StringIO()
            namespace = {'pd': pd, 'plt': plt, 'os': os}

            print(f"DEBUG: Ejecutando análisis local sobre {clean_path}...")

            with contextlib.redirect_stdout(output_capturado):
                exec(codigo_python, namespace)

            resultados_finales = output_capturado.getvalue()

            # 6. SEGUNDA LLAMADA: Traducir resultados a lenguaje humano (con contexto de documentos si existe)
            context_instruction = ""
            if document_context:
                context_instruction = (
                    f" Además, tienes este contexto de documentos de negocio del usuario:\n\n{document_context}\n\n"
                    "Cuando sea relevante, integra esta información para dar insights más profundos "
                    "(ej.: si los datos muestran una caída en ventas y un documento menciona cierre por mantenimiento, relaciónalo)."
                )
            prompt_final = (
                f"El código se ejecutó con éxito. Estos son los resultados técnicos:\n{resultados_finales}\n\n"
                f"Basado en esto, responde al usuario como Analista Senior de InsightFlow. "
                f"No menciones el código, solo da las conclusiones y hallazgos en lenguaje natural (números, años, tendencias). "
                f"{context_instruction} {LENGTH_INSTRUCTION}"
            )

            respuesta_final = self.model.generate_content(prompt_final)
            return self._cap_response_length(respuesta_final.text)

        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            return f"Error en ejecución: {e}\n\nCódigo generado: {codigo_python}"
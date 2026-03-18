"""
AnalystAgent: análisis de datos con Gemini (vía ModelManager) y contexto de documentos.
Genera código Python para analizar CSV/Excel, lo ejecuta y resume resultados en lenguaje natural.
"""
import io
import contextlib
import os
import re
from typing import Optional, List, Tuple

import google.generativeai as genai
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv

from agents.model_manager import ModelManager

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Modelos con respaldo ante 429 (ModelManager aplica cooldown)
DEFAULT_MODEL_NAMES: List[str] = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-3-flash-preview",
]

_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")
MAX_RESPONSE_CHARS = 4096 - 30  # Límite Telegram
LENGTH_INSTRUCTION = (
    f"LÍMITE ESTRICTO: tu respuesta debe tener MÁXIMO {MAX_RESPONSE_CHARS} caracteres (límite del canal). "
    "Redacta de forma concisa: prioriza hallazgos clave, evita listas interminables y repeticiones. "
    "Si el análisis es extenso, resume en secciones breves con los números y conclusiones más importantes."
)

# Indicadores de que el texto es código de análisis (pandas/archivo)
_CODE_INDICATORS = ("read_csv", "read_excel", "pd.", "import pandas", "import pd")


def _get_latest_data_file_in_folder(user_data_folder: str) -> Optional[str]:
    """Ruta del archivo CSV/XLSX más reciente por mtime en la carpeta del usuario."""
    if not user_data_folder or not os.path.isdir(user_data_folder):
        return None
    candidates = []
    for name in os.listdir(user_data_folder):
        if not name.lower().endswith(_DATA_EXTENSIONS):
            continue
        path = os.path.join(user_data_folder, name)
        try:
            candidates.append((os.path.getmtime(path), path))
        except OSError:
            continue
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def _read_schema_sample(path: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Muestra de 2 filas para esquema. Soporta CSV (varios encodings) y Excel. Retorna (DataFrame, encoding o None)."""
    path_lower = path.lower()
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, nrows=2), None
    for encoding in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            return pd.read_csv(path, nrows=2, encoding=encoding), encoding
        except (UnicodeDecodeError, Exception):
            continue
    return pd.read_csv(path, nrows=2, encoding="latin-1"), "latin-1"


class AnalystAgent:
    """Analista que genera código Python sobre datos del usuario y resume resultados con Gemini (fallback 429)."""

    def __init__(self, knowledge_agent=None, model_names: Optional[List[str]] = None):
        self.knowledge_agent = knowledge_agent
        identity = (
            "Eres el cerebro analítico de InsightFlow, una plataforma de BI avanzada.\n"
            "Tu propósito es transformar datos complejos en insights de negocio claros.\n"
            "Siempre te presentas como el Analista Senior de InsightFlow.\n"
            "Cuando hay archivos, generas código Python local para analizarlos.\n"
            f"Siempre que des una respuesta en texto, respétala máximo {MAX_RESPONSE_CHARS} caracteres (límite del canal): sé conciso, prioriza hallazgos clave."
        )
        self._manager = ModelManager(
            model_names=model_names or DEFAULT_MODEL_NAMES,
            system_instruction=identity,
            api_key=os.getenv("GEMINI_API_KEY"),
        )

    def _generate(self, content: str, **kwargs):
        """Generación con fallback 429 vía ModelManager."""
        return self._manager.generate_content(content, **kwargs)

    def _cap(self, text: str) -> str:
        """Recorta al límite de mensaje Telegram."""
        if not text or len(text) <= MAX_RESPONSE_CHARS:
            return text or ""
        return text[: MAX_RESPONSE_CHARS - 50].rstrip() + "\n\n[— Respuesta recortada por límite del mensaje.]"

    def _extraer_codigo(self, texto_ia: str) -> str:
        """Extrae el bloque ```python ... ``` de la respuesta."""
        match = re.search(r"```python\s*(.*?)\s*```", texto_ia, re.DOTALL)
        if match:
            return match.group(1)
        return texto_ia.replace("```python", "").replace("```", "").strip()

    def _sanitize_code(self, codigo: str) -> str:
        """Elimina BOM y caracteres que rompen exec (¡, ¿)."""
        if not codigo:
            return codigo
        codigo = codigo.lstrip("\ufeff\u00a0").replace("\u00a1", "# ").replace("\u00bf", "# ")
        return codigo

    def _looks_like_python_code(self, codigo: str) -> bool:
        """True si parece código de análisis (pandas/archivo) y no solo comentarios."""
        if not codigo or not codigo.strip():
            return False
        codigo = codigo.strip()
        has_analysis = any(ind in codigo for ind in _CODE_INDICATORS)
        non_comment_lines = [l for l in codigo.splitlines() if l.strip() and not l.strip().startswith("#")]
        return bool(has_analysis and non_comment_lines)

    def _get_document_context(self, user_query: str, top_k: int = 5) -> str:
        """Contexto de documentos indexados (búsqueda semántica). Vacío si no hay knowledge_agent o resultados."""
        if not self.knowledge_agent:
            return ""
        try:
            results = self.knowledge_agent.search(user_query, top_k=top_k)
            if not results:
                return ""
            lines = [
                f"[Fuente: {r.get('source', 'documento')}]\n{(r.get('text') or '').strip()}"
                for r in results if (r.get("text") or "").strip()
            ]
            if not lines:
                return ""
            return "CONTEXTO DE DOCUMENTOS INDEXADOS (reportes, reglas de negocio, etc.):\n\n" + "\n\n---\n\n".join(lines)
        except Exception as e:
            print(f"DEBUG: búsqueda semántica fallida: {e}")
            return ""

    def _answer_without_data_file(self, user_query: str, document_context: str) -> str:
        """Respuesta cuando no hay archivo de datos (solo pregunta y opcionalmente contexto de documentos)."""
        if document_context:
            prompt = (
                f"{document_context}\n\nPREGUNTA DEL USUARIO: {user_query}\n\n"
                "Responde como Analista Senior de InsightFlow, integrando si aplica la información de los documentos anteriores. "
                + LENGTH_INSTRUCTION
            )
        else:
            prompt = user_query + "\n\n" + LENGTH_INSTRUCTION
        response = self._generate(prompt)
        return self._cap(response.text)

    def _build_read_instruction(self, clean_path: str, path_lower: str, csv_encoding: Optional[str]) -> str:
        """Instrucción para cargar el archivo (read_csv/read_excel y encoding si aplica)."""
        if path_lower.endswith((".xlsx", ".xls")):
            return f"Usa pd.read_excel('{clean_path}') para cargar el archivo."
        if csv_encoding and csv_encoding != "utf-8":
            return f"Usa pd.read_csv('{clean_path}', encoding='{csv_encoding}') para cargar el archivo (este CSV no es UTF-8)."
        return f"Usa pd.read_csv('{clean_path}') para cargar el archivo."

    def _build_code_prompt(
        self,
        clean_path: str,
        read_instruction: str,
        schema_info: str,
        document_context: str,
        user_query: str,
        plot_filename: str,
    ) -> str:
        """Prompt para que el modelo genere código de análisis."""
        system = (
            "Eres el cerebro analítico de InsightFlow basado en Gemini.\n"
            "TU OBJETIVO: Generar código Python para analizar archivos locales masivos.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi sistema lo lea.\n"
            f"2. Ruta exacta del archivo: '{clean_path}'. {read_instruction}\n"
            f"3. Si se pide una gráfica, usa matplotlib y guarda SIEMPRE como '{plot_filename}' (plt.savefig + plt.close()).\n"
            "4. Imprime con print() todos los números, años y resultados clave del análisis.\n"
            "5. Responde con análisis profesional y el código dentro de un bloque ```python.\n"
            "6. Si el usuario solo saluda o dice que va a subir archivo (sin pedir análisis), responde en lenguaje natural SIN código."
        )
        doc_block = f"\n\n{document_context}\n\n" if document_context else ""
        return f"{system}\n\nESTRUCTURA DEL ARCHIVO:\n{schema_info}{doc_block}PREGUNTA DEL USUARIO: {user_query}"

    def _run_code_and_summarize(
        self,
        codigo_python: str,
        clean_path: str,
        document_context: str,
    ) -> str:
        """Ejecuta el código generado, captura stdout y pide al modelo un resumen en lenguaje natural."""
        output = io.StringIO()
        namespace = {"pd": pd, "plt": plt, "os": os}
        print(f"DEBUG: Ejecutando análisis local sobre {clean_path}...")
        with contextlib.redirect_stdout(output):
            exec(codigo_python, namespace)
        resultados = output.getvalue()

        context_instruction = ""
        if document_context:
            context_instruction = (
                f" Además, contexto de documentos del usuario:\n\n{document_context}\n\n"
                "Cuando sea relevante, integra esta información para dar insights más profundos."
            )
        prompt_final = (
            f"El código se ejecutó con éxito. Resultados técnicos:\n{resultados}\n\n"
            "Responde como Analista Senior de InsightFlow. No menciones el código, solo conclusiones y hallazgos en lenguaje natural. "
            f"{context_instruction} {LENGTH_INSTRUCTION}"
        )
        response = self._generate(prompt_final)
        return self._cap(response.text)

    async def analyze_data(
        self,
        user_query: str,
        local_file_path: Optional[str] = None,
        user_data_folder: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> str:
        """
        Analiza según la pregunta del usuario.
        - local_file_path: archivo recién subido (opcional).
        - user_data_folder: carpeta del usuario (data/{chat_id}); si no hay archivo, se usa el más reciente ahí.
        Usa búsqueda semántica en documentos indexados (KnowledgeAgent) para enriquecer contexto.
        """
        document_context = self._get_document_context(user_query)
        file_path = local_file_path or (user_data_folder and _get_latest_data_file_in_folder(user_data_folder))

        if not file_path or not os.path.exists(file_path):
            return self._answer_without_data_file(user_query, document_context)

        try:
            df_sample, csv_encoding = _read_schema_sample(file_path)
            schema_info = f"Columnas: {list(df_sample.columns)}\nMuestra: {df_sample.to_dict('records')}"
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        clean_path = file_path.replace("\\", "/")
        path_lower = clean_path.lower()
        read_instruction = self._build_read_instruction(clean_path, path_lower, csv_encoding)
        plot_filename = f"output_plot_{chat_id}.png" if chat_id else "output_plot.png"
        prompt = self._build_code_prompt(
            clean_path, read_instruction, schema_info, document_context, user_query, plot_filename
        )

        try:
            response = self._generate(prompt)
            respuesta_texto = response.text
            codigo_python = self._sanitize_code(self._extraer_codigo(respuesta_texto))
        except Exception as e:
            return f"Error de comunicación con el modelo de análisis: {str(e)}"

        if not self._looks_like_python_code(codigo_python):
            return self._cap(respuesta_texto)

        try:
            return self._run_code_and_summarize(codigo_python, clean_path, document_context)
        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            return f"Error en ejecución: {e}\n\nCódigo generado: {codigo_python}"

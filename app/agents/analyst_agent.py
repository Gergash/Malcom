"""
AnalystAgent: análisis de datos con Gemini (vía ModelManager) y contexto de documentos.
Genera código Python para analizar CSV/Excel, lo ejecuta y resume resultados en lenguaje natural.
Cada usuario (chat_id) tiene su propia base vectorial; los embeddings nunca se mezclan.
PDFs y documentos se manejan exclusivamente vía KnowledgeAgent (contexto vectorial).
"""
import functools
import io
import os
import re
from typing import Optional, List, Dict

import google.generativeai as genai
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv

try:
    from app.agents.model_manager import ModelManager
    from app.agents.knowledge_agent import KnowledgeAgent, DOC_EXTENSIONS
    from app.agents.report_generator import (
        generar_reporte_excel_avanzado,
        generar_reporte_pdf,
        _read_schema_sample,
    )
    from app.agents.report_generator_agent import build_report_translator_instructions
    from app.api.schemas import ReportConfig
except ModuleNotFoundError:
    from agents.model_manager import ModelManager
    from agents.knowledge_agent import KnowledgeAgent, DOC_EXTENSIONS
    from agents.report_generator import (
        generar_reporte_excel_avanzado,
        generar_reporte_pdf,
        _read_schema_sample,
    )
    from agents.report_generator_agent import build_report_translator_instructions
    from api.schemas import ReportConfig
try:
    # Cuando se ejecuta desde la raíz: `python -m app.main`
    from app.executor import safe_exec
except ModuleNotFoundError:
    # Cuando se ejecuta dentro de `app/`: `python main.py`
    from executor import safe_exec

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

DEFAULT_MODEL_NAMES: List[str] = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-3-flash-preview",
]

_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")
MAX_RESPONSE_CHARS = 4096 - 30
LENGTH_INSTRUCTION = (
    f"LÍMITE ESTRICTO: tu respuesta debe tener MÁXIMO {MAX_RESPONSE_CHARS} caracteres (límite del canal). "
    "Redacta de forma concisa: prioriza hallazgos clave, evita listas interminables y repeticiones. "
    "Si el análisis es extenso, resume en secciones breves con los números y conclusiones más importantes."
)

_CODE_INDICATORS = (
    "read_csv",
    "read_excel",
    "pd.",
    "import pandas",
    "import pd",
    "generar_reporte_pdf",
    "generar_reporte_excel_avanzado",
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _is_document_file(path: str) -> bool:
    """True si el archivo es un documento indexable (PDF, DOCX, TXT) que NO se puede leer con pandas."""
    return path.lower().endswith(DOC_EXTENSIONS)


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



class AnalystAgent:
    """
    Analista que genera código Python sobre datos del usuario y resume resultados con Gemini.
    Cada chat_id obtiene su propio KnowledgeAgent (base vectorial aislada en data/{chat_id}/vector_db/).
    PDFs/documentos se resuelven exclusivamente por contexto vectorial; nunca se intentan leer con pandas.
    """

    def __init__(self, model_names: Optional[List[str]] = None):
        identity = (
            "Eres el cerebro analítico de InsightFlow, una plataforma de BI avanzada.\n"
            "Tu propósito es transformar datos complejos en insights de negocio claros.\n"
            "Siempre te presentas como el Analista Senior de InsightFlow.\n"
            "Cuando hay archivos CSV/Excel, generas código Python local para analizarlos.\n"
            "Para informes PDF existe `generar_reporte_pdf` y para Excel `generar_reporte_excel_avanzado` inyectadas en ejecución; "
            "el contexto de manuales va en `contexto_documentos`. La plataforma envía reporte_final.pdf y reporte_final.xlsx al chat cuando se generan.\n"
            "Cuando hay PDFs o documentos indexados, usas el contexto textual proporcionado (nunca código para leerlos).\n"
            f"Siempre que des una respuesta en texto, respétala máximo {MAX_RESPONSE_CHARS} caracteres (límite del canal): sé conciso, prioriza hallazgos clave."
        )
        self._manager = ModelManager(
            model_names=model_names or DEFAULT_MODEL_NAMES,
            system_instruction=identity,
            api_key=os.getenv("GEMINI_API_KEY"),
        )
        self._knowledge_agents: Dict[int, KnowledgeAgent] = {}
        self._pending_pdf_report_path: Optional[str] = None
        self._pending_excel_report_path: Optional[str] = None

    def peek_pending_pdf_report(self) -> Optional[str]:
        """Ruta absoluta del último reporte_final.pdf registrado tras exec (si lo hubo)."""
        return self._pending_pdf_report_path

    def clear_pending_pdf_report(self) -> None:
        """Limpia la referencia al PDF pendiente (p. ej. tras enviarlo al chat)."""
        self._pending_pdf_report_path = None

    def peek_pending_excel_report(self) -> Optional[str]:
        """Ruta absoluta del último reporte_final.xlsx registrado tras exec (si lo hubo)."""
        return self._pending_excel_report_path

    def clear_pending_excel_report(self) -> None:
        self._pending_excel_report_path = None

    def get_knowledge_agent(self, chat_id: int) -> KnowledgeAgent:
        """Devuelve el KnowledgeAgent para un chat_id, creándolo si no existe."""
        if chat_id not in self._knowledge_agents:
            vector_db_path = os.path.join(_PROJECT_ROOT, "data", str(chat_id), "vector_db")
            self._knowledge_agents[chat_id] = KnowledgeAgent(vector_db_path=vector_db_path)
        return self._knowledge_agents[chat_id]

    def _generate(self, content: str, **kwargs):
        """Generación con fallback 429 vía ModelManager."""
        return self._manager.generate_content(content, **kwargs)

    def _cap(self, text: str) -> str:
        """Recorta al límite de mensaje Telegram."""
        if not text or len(text) <= MAX_RESPONSE_CHARS:
            return text or ""
        return text[: MAX_RESPONSE_CHARS - 50].rstrip() + "\n\n[— Respuesta recortada por límite del mensaje.]"

    def _extraer_codigo(self, texto_ia: str) -> str:
        match = re.search(r"```python\s*(.*?)\s*```", texto_ia, re.DOTALL)
        if match:
            return match.group(1)
        return texto_ia.replace("```python", "").replace("```", "").strip()

    def _sanitize_code(self, codigo: str) -> str:
        if not codigo:
            return codigo
        return codigo.lstrip("\ufeff\u00a0").replace("\u00a1", "# ").replace("\u00bf", "# ")

    def _looks_like_python_code(self, codigo: str) -> bool:
        if not codigo or not codigo.strip():
            return False
        codigo = codigo.strip()
        has_analysis = any(ind in codigo for ind in _CODE_INDICATORS)
        non_comment_lines = [l for l in codigo.splitlines() if l.strip() and not l.strip().startswith("#")]
        return bool(has_analysis and non_comment_lines)

    def _get_document_context(self, user_query: str, chat_id: Optional[int] = None, top_k: int = 5) -> str:
        """Contexto de documentos indexados del usuario (búsqueda semántica aislada por chat_id)."""
        if chat_id is None:
            return ""
        ka = self.get_knowledge_agent(chat_id)
        try:
            results = ka.search(user_query, top_k=top_k)
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
            print(f"DEBUG: búsqueda semántica fallida (chat_id={chat_id}): {e}")
            return ""

    # ── Respuestas sin archivo de datos (solo contexto documental) ────────

    def _answer_document_only(self, user_query: str, document_context: str) -> str:
        """Respuesta basada exclusivamente en el contexto vectorial de documentos (PDFs, DOCX, TXT)."""
        if not document_context:
            return self._cap(
                "No encontré información relevante en los documentos indexados. "
                "¿Podrías subir el PDF o documento que deseas consultar?"
            )
        prompt = (
            f"{document_context}\n\n"
            "PREGUNTA DEL USUARIO: " + user_query + "\n\n"
            "INSTRUCCIONES: Responde ÚNICAMENTE con base en la información de los documentos proporcionados arriba. "
            "No inventes datos. Si la información no está en los documentos, indícalo claramente. "
            "Responde como Analista Senior de InsightFlow. "
            + LENGTH_INSTRUCTION
        )
        response = self._generate(prompt)
        return self._cap(response.text)

    def _answer_without_data_file(self, user_query: str, document_context: str) -> str:
        """Respuesta cuando no hay archivo de datos ni documentos relevantes."""
        if document_context:
            return self._answer_document_only(user_query, document_context)
        prompt = user_query + "\n\n" + LENGTH_INSTRUCTION
        response = self._generate(prompt)
        return self._cap(response.text)

    # ── Construcción de prompts para generación de código ────────────────

    def _build_read_instruction(self, clean_path: str, path_lower: str, csv_encoding: Optional[str]) -> str:
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
        report_pdf_path: str,
        report_excel_path: str,
        report_config: Optional[ReportConfig] = None,
    ) -> str:
        system = (
            "Eres el cerebro analítico de InsightFlow basado en Gemini.\n"
            "TU OBJETIVO: Generar código Python para analizar archivos locales masivos.\n"
            "REGLAS CRÍTICAS:\n"
            "1. El archivo es muy grande. NO intentes leerlo tú. Genera código para que mi sistema lo lea.\n"
            f"2. Ruta exacta del archivo: '{clean_path}'. {read_instruction}\n"
            f"3. Si se pide una gráfica, usa matplotlib y guarda SIEMPRE como '{plot_filename}' (plt.savefig + plt.close()).\n"
            "4. Justo después de cargar el DataFrame, imprime print('Columnas detectadas:', df.columns.tolist()) "
            "para diagnóstico. Luego imprime con print() todos los números, años y resultados clave del análisis.\n"
            "5. Responde con análisis profesional y el código dentro de un bloque ```python.\n"
            "6. Si el usuario solo saluda o dice que va a subir archivo (sin pedir análisis), responde en lenguaje natural SIN código.\n"
            "7. PROHIBIDO: NUNCA generes código con pd.read_csv(), pd.read_excel(), open() ni ninguna "
            "función de lectura sobre archivos .pdf, .docx o .txt. Esos documentos ya están indexados y "
            "su contenido se proporciona como CONTEXTO TEXTUAL en este prompt. Úsalo directamente.\n"
            "8. REGLA CRÍTICA DE PDF: ESTÁ ESTRICTAMENTE PROHIBIDO importar FPDF o fpdf, o escribir clases "
            "u otra lógica de diseño PDF. Si el usuario pide un 'informe' o 'reporte' en PDF, la creación del "
            "archivo debe hacerse ÚNICAMENTE con la función ya inyectada en el entorno, exactamente así: "
            f"generar_reporte_pdf(contexto_documentos, r'{report_pdf_path}'). "
            "No añadas llamadas a FPDF, pdf.output manual ni layouts propios. Opcional: un print() breve "
            "tras la llamada (ej. confirmación). El contexto de manuales va en la variable "
            "`contexto_documentos` (no la transcribas en el código). "
            f"Si generas gráfica (regla 3), guarda con '{plot_filename}': el backend la adjuntará al PDF si existe. "
            "Para el análisis de datos (CSV, cálculos, gráficas) sigue las reglas 1-4; el PDF es solo esa llamada.\n"
            "9. REGLA CRÍTICA DE EXCEL: ESTÁ ESTRICTAMENTE PROHIBIDO importar xlsxwriter o escribir lógica de "
            "diseño de hojas, formatos o tablas a mano. Si el usuario pide un Excel con datos, texto o gráficas, "
            "la generación del archivo debe hacerse ÚNICAMENTE con la función ya inyectada, exactamente así: "
            f"generar_reporte_excel_avanzado(df, contexto_documentos, r'{report_excel_path}'). "
            "`df` es el DataFrame que tú cargaste del CSV/Excel en tu propio código (reglas 1-2); no está "
            "preinyectado. Opcional: print() del valor de retorno (mensaje LOG/ERROR). "
            f"Si generas gráfica (regla 3), usa '{plot_filename}': el backend la insertará en el Excel si existe. "
            "No añadas otra lógica de exportación Excel.\n"
            "10. REGLA DE VERACIDAD DE DATOS (NIVEL SENIOR): Cuando generes código Python para gráficas, "
            "DEBES PRIORIZAR EXCLUSIVAMENTE los datos extraídos del archivo CSV/Excel cargado o del "
            "contexto_documentos (OCR/Vectores de los archivos subidos). "
            "ESTÁ PROHIBIDO crear arrays de datos simulados (ej: valores = [10, 20, 30]) basándote en "
            "suposiciones del texto, a menos que el usuario use la palabra clave 'SIMULAR' o 'DURMIE'.\n"
            "11. VERIFICACIÓN DE ORIGEN: Antes de generar cualquier plt.plot(), plt.bar(), sns.lineplot() u "
            "otra función de gráfica, verifica el origen de los datos: ¿Vienen del DataFrame cargado del archivo? "
            "¿Vienen explícitamente del contexto_documentos? "
            "Si no hay números explícitos en ninguna de las dos fuentes, DETENTE y genera ÚNICAMENTE un "
            "print() con el mensaje: 'SOLICITUD_DATOS: No encontré números suficientes para graficar. "
            "Por favor proporciona los datos específicos que deseas visualizar.' "
            "PROHIBIDO generar plt.plot() ni cualquier función de visualización con datos sintéticos no solicitados.\n"
            "12. INFORME CON CONTRATO DE ESTILO: Si existe un bloque REPORTE — COMUNICACIÓN CORPORATIVA más abajo, "
            "redacta el contenido textual que irá a PDF/Excel (p. ej. vía contexto_documentos o resumen ejecutivo) "
            "cumpliendo ese contrato: audiencia, tono y dialecto. Los colores y tamaños de fuente en el archivo "
            "los aplica el sistema; no los codifiques en Python."
        )
        doc_block = ""
        if document_context:
            doc_block = (
                f"\n\n{document_context}\n\n"
                "IMPORTANTE: El texto anterior proviene de documentos del usuario (PDFs, reportes, etc.) "
                "ya indexados. En el código NO copies este bloque: en ejecución está en `contexto_documentos`. "
                "Para PDF usa generar_reporte_pdf (regla 8); para Excel generar_reporte_excel_avanzado (regla 9). "
                "NO leas archivos .pdf con código."
            )
        style_block = build_report_translator_instructions(report_config)
        return (
            f"{system}{style_block}\n\nESTRUCTURA DEL ARCHIVO:\n{schema_info}{doc_block}\n\n"
            f"PREGUNTA DEL USUARIO: {user_query}"
        )

    # ── Ejecución de código y resumen con cruce documental ───────────────

    def _run_code_and_summarize(
        self,
        codigo_python: str,
        clean_path: str,
        document_context: str,
        report_pdf_path: str,
        report_excel_path: str,
        plot_filename: str,
        report_config: Optional[ReportConfig] = None,
    ) -> str:
        """Ejecuta el código generado, captura stdout y pide al modelo un resumen cruzado."""
        ruta_img = plot_filename or None
        generar_pdf = functools.partial(
            generar_reporte_pdf, ruta_grafica=ruta_img, report_config=report_config
        )
        generar_excel = functools.partial(
            generar_reporte_excel_avanzado, ruta_grafica=ruta_img, report_config=report_config
        )
        namespace = {
            "pd": pd,
            "plt": plt,
            "os": os,
            "contexto_documentos": document_context or "",
            "generar_reporte_pdf": generar_pdf,
            "generar_reporte_excel_avanzado": generar_excel,
        }
        print(f"DEBUG: Ejecutando análisis local sobre {clean_path}...")
        prev_cwd = os.getcwd()
        try:
            if clean_path:
                data_dir = os.path.dirname(os.path.abspath(clean_path))
                if data_dir and os.path.isdir(data_dir):
                    os.chdir(data_dir)
            result = safe_exec(codigo_python, namespace)
        finally:
            os.chdir(prev_cwd)
        resultados = result.stdout
        if not result.ok:
            raise result.error  # manejado por analyze_data (mensaje incluye código)

        abs_report = os.path.abspath(report_pdf_path)
        if os.path.isfile(abs_report):
            self._pending_pdf_report_path = abs_report

        abs_xlsx = os.path.abspath(report_excel_path)
        if os.path.isfile(abs_xlsx):
            self._pending_excel_report_path = abs_xlsx

        if document_context:
            cross_reference = (
                f"\n\nAdemás, el usuario tiene los siguientes documentos indexados (PDFs, reportes, reglas de negocio):\n\n"
                f"{document_context}\n\n"
                "INSTRUCCIÓN DE CRUCE: Realiza un cruce narrativo entre los RESULTADOS NUMÉRICOS del análisis "
                "de datos (CSV/Excel) y la INFORMACIÓN TEXTUAL de los documentos (PDFs). "
                "Ejemplo: si el CSV muestra una caída de ventas en marzo, y el PDF menciona una reestructuración "
                "en ese período, conecta ambos hallazgos en tu respuesta. "
                "Presenta las conclusiones de forma integrada, no como dos bloques separados."
            )
        else:
            cross_reference = ""

        narrative_contract = build_report_translator_instructions(report_config)
        prompt_final = (
            f"El código se ejecutó con éxito. Resultados técnicos del análisis de datos:\n{resultados}\n\n"
            f"{narrative_contract}"
            "Responde como Analista Senior de InsightFlow. No menciones el código, solo conclusiones y "
            f"hallazgos en lenguaje natural.{cross_reference} {LENGTH_INSTRUCTION}"
        )
        response = self._generate(prompt_final)
        return self._cap(response.text)

    # ── Punto de entrada principal ───────────────────────────────────────

    async def analyze_data(
        self,
        user_query: str,
        local_file_path: Optional[str] = None,
        user_data_folder: Optional[str] = None,
        chat_id: Optional[int] = None,
        report_config: Optional[ReportConfig] = None,
    ) -> str:
        """
        Analiza según la pregunta del usuario.
        - Si el archivo es un PDF/documento: responde exclusivamente con el contexto vectorial.
        - Si es CSV/Excel: genera y ejecuta código, y cruza resultados con contexto documental si existe.
        - Si el local_file_path es un PDF pero hay un CSV/Excel en la carpeta: analiza el CSV y cruza con el PDF.
        """
        document_context = self._get_document_context(user_query, chat_id=chat_id)
        self._pending_pdf_report_path = None
        self._pending_excel_report_path = None

        # Separar documentos (PDF/DOCX/TXT) de archivos de datos (CSV/Excel)
        data_file_path: Optional[str] = None
        if local_file_path and not _is_document_file(local_file_path):
            data_file_path = local_file_path
        if not data_file_path and user_data_folder:
            data_file_path = _get_latest_data_file_in_folder(user_data_folder)

        # Sin archivo de datos → respuesta basada solo en documentos o conversacional
        if not data_file_path or not os.path.exists(data_file_path):
            if local_file_path and _is_document_file(local_file_path):
                return self._answer_document_only(user_query, document_context)
            return self._answer_without_data_file(user_query, document_context)

        # Archivo de datos (CSV/Excel) presente → generar código de análisis
        try:
            df_sample, csv_encoding = _read_schema_sample(data_file_path)
            schema_info = f"Columnas: {list(df_sample.columns)}\nMuestra: {df_sample.to_dict('records')}"
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}"

        clean_path = data_file_path.replace("\\", "/")
        path_lower = clean_path.lower()
        read_instruction = self._build_read_instruction(clean_path, path_lower, csv_encoding)
        plot_filename = f"output_plot_{chat_id}.png" if chat_id else "output_plot.png"
        report_pdf_path = (
            os.path.join(os.path.abspath(user_data_folder), "reporte_final.pdf")
            if user_data_folder
            else os.path.join(_PROJECT_ROOT, "reporte_final.pdf")
        )
        report_excel_path = (
            os.path.join(os.path.abspath(user_data_folder), "reporte_final.xlsx")
            if user_data_folder
            else os.path.join(_PROJECT_ROOT, "reporte_final.xlsx")
        )
        prompt = self._build_code_prompt(
            clean_path,
            read_instruction,
            schema_info,
            document_context,
            user_query,
            plot_filename,
            report_pdf_path.replace("\\", "/"),
            report_excel_path.replace("\\", "/"),
            report_config=report_config,
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
            return self._run_code_and_summarize(
                codigo_python,
                clean_path,
                document_context,
                report_pdf_path,
                report_excel_path,
                plot_filename,
                report_config=report_config,
            )
        except Exception as e:
            print(f"Error ejecutando código local: {e}")
            # Pedir al modelo que corrija el error usando el esquema real del archivo
            try:
                fix_prompt = (
                    f"El siguiente código Python falló con el error: {e}\n\n"
                    f"Esquema REAL del archivo (usa EXACTAMENTE estos nombres de columna):\n{schema_info}\n\n"
                    "Corrige el código para que use exclusivamente los nombres de columna del esquema real. "
                    "Responde SOLO con el bloque ```python corregido."
                )
                fix_response = self._generate(fix_prompt)
                codigo_corregido = self._sanitize_code(self._extraer_codigo(fix_response.text))
                if self._looks_like_python_code(codigo_corregido):
                    return self._run_code_and_summarize(
                        codigo_corregido,
                        clean_path,
                        document_context,
                        report_pdf_path,
                        report_excel_path,
                        plot_filename,
                        report_config=report_config,
                    )
            except Exception as e2:
                print(f"Error en reintento de corrección: {e2}")
            return self._cap(
                f"Encontré un problema al analizar el archivo: {e}. "
                "Por favor verifica que el archivo CSV esté bien formado o intenta con otra pregunta."
            )

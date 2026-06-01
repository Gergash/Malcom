"""
AnalystAgent: análisis de datos con Gemini (vía ModelManager) y contexto de documentos.
Genera código Python para analizar CSV/Excel, lo ejecuta y resume resultados en lenguaje natural.
Cada usuario (chat_id) tiene su propia base vectorial; los embeddings nunca se mezclan.
PDFs y documentos se manejan exclusivamente vía KnowledgeAgent (contexto vectorial).
"""
import functools
import io
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import google.generativeai as genai
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv

try:
    from app.agents.model_manager import ModelManager
    from app.agents.compliance_agent import ComplianceAgent
    from app.agents.data_cleaner import clean_structured_dataframe
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
    from agents.compliance_agent import ComplianceAgent
    from agents.data_cleaner import clean_structured_dataframe
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
    from app.core.echarts_builder import (
        aggregate_and_build_option,
        dataframe_to_echarts_option,
        build_bar_option,
        build_line_option,
        build_pie_option,
        build_horizontal_bar_option,
        build_scatter_option,
        build_heatmap_option,
        build_stacked_bar_option,
        correlation_heatmap_from_df,
    )
    from app.agents.report_generator import generar_reporte_premium_pdf
except ModuleNotFoundError:
    # Cuando se ejecuta dentro de `app/`: `python main.py`
    from executor import safe_exec
    from core.echarts_builder import (
        aggregate_and_build_option,
        dataframe_to_echarts_option,
        build_bar_option,
        build_line_option,
        build_pie_option,
        build_horizontal_bar_option,
        build_scatter_option,
        build_heatmap_option,
        build_stacked_bar_option,
        correlation_heatmap_from_df,
    )
    from agents.report_generator import generar_reporte_premium_pdf

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
_HEADER_SCAN_LIMIT = 12
_TRANSACTIONAL_HEADER_KEYWORDS = (
    "cif",
    "fob",
    "cantidad",
    "arancel",
    "aduana",
    "fecha",
    "nit",
    "valor",
    "total",
    "descripcion",
    "documento",
    "factura",
    "concepto",
    "debito",
    "credito",
    "saldo",
)
_COMPLEX_DELIMITERS = ("|", ";")


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


def _normalize_header_name(value: Any, idx: int) -> str:
    txt = str(value).strip() if value is not None else ""
    if not txt or txt.lower() in {"nan", "none"}:
        txt = f"col_{idx + 1}"
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _score_header_candidate(cells: List[Any]) -> int:
    score = 0
    for cell in cells:
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            continue
        txt = str(cell).strip().lower()
        if not txt or txt in {"nan", "none"}:
            continue
        score += sum(1 for kw in _TRANSACTIONAL_HEADER_KEYWORDS if kw in txt)
    return score


def _dedupe_headers(headers: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for h in headers:
        base = h
        if base not in seen:
            seen[base] = 1
            out.append(base)
            continue
        seen[base] += 1
        out.append(f"{base}_{seen[base]}")
    return out


def _expand_complex_delimiters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Si el archivo llegó en una sola columna masiva, intenta reconstruir
    la tabla real con delimitadores corporativos frecuentes.
    """
    if df.empty or df.shape[1] != 1:
        return df
    col = df.iloc[:, 0].astype(str)
    candidate: Optional[str] = None
    for sep in _COMPLEX_DELIMITERS:
        # Exigimos presencia consistente para evitar expandir textos libres.
        ratio = float(col.str.contains(re.escape(sep), regex=True, na=False).mean())
        if ratio >= 0.6:
            candidate = sep
            break
    if not candidate:
        return df
    expanded = col.str.split(candidate, expand=True)
    return expanded


def _read_raw_dataframe(file_path: str, csv_encoding: Optional[str]) -> pd.DataFrame:
    path_lower = file_path.lower()
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_path, header=None, dtype=str)

    base_kwargs: Dict[str, Any] = {
        "header": None,
        "dtype": str,
        "engine": "python",
    }
    if csv_encoding and csv_encoding != "utf-8":
        base_kwargs["encoding"] = csv_encoding

    # Intento 1: autodetección de separador.
    try:
        return pd.read_csv(file_path, sep=None, **base_kwargs)
    except Exception:
        pass
    # Intento 2: separador por defecto.
    return pd.read_csv(file_path, **base_kwargs)


def _load_sidecar_metadata_context(file_path: str) -> str:
    """
    Carga metadata sidecar generado por data_cleaner (archivo .meta.json) para
    enriquecer ComplianceAgent sin tocar el DataFrame limpio.
    """
    try:
        data_dir = os.path.dirname(os.path.abspath(file_path))
        base = os.path.splitext(os.path.basename(file_path))[0]
        specific = os.path.join(data_dir, f"{base}.meta.json")
        generic = os.path.join(data_dir, ".meta.json")
        target = specific if os.path.isfile(specific) else generic
        if not os.path.isfile(target):
            return ""
        with open(target, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            return ""
        return "METADATA SIDECAR (data_cleaner):\n" + json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return ""


def load_structured_dataframe(
    file_path: str,
    csv_encoding: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> pd.DataFrame:
    """
    Pipeline silencioso de ingesta:
    1) Detecta y descarta metadatos previos al encabezado real.
    2) Expande columnas cuando el archivo llegó concatenado por '|' o ';'.
    3) Limpia nulos redundantes sin interacción con el usuario.
    """
    # Delegamos el pipeline robusto al módulo especializado app/agents/data_cleaner.py
    # para mantener la ingeniería de datos determinista separada del orquestador.
    return clean_structured_dataframe(file_path, csv_encoding=csv_encoding, chat_id=chat_id)



class AnalystAgent:
    """
    Analista que genera código Python sobre datos del usuario y resume resultados con Gemini.
    Cada chat_id obtiene su propio KnowledgeAgent (base vectorial aislada en data/{chat_id}/vector_db/).
    PDFs/documentos se resuelven exclusivamente por contexto vectorial; nunca se intentan leer con pandas.
    """

    def __init__(self, model_names: Optional[List[str]] = None):
        identity = (
            "Eres el cerebro analítico de InsightFlow, una plataforma de BI avanzada.\n"
            "Actúas como Ingeniero de Datos Senior experto en idiosincrasia de archivos corporativos y gubernamentales de Colombia "
            "(DIAN, RIPS, extractos bancarios).\n"
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
        self._compliance_agent = ComplianceAgent(model_names=model_names or DEFAULT_MODEL_NAMES)
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

    def _answer_document_only(
        self, user_query: str, document_context: str, require_strict_data: bool = False
    ) -> str:
        """Respuesta basada exclusivamente en el contexto vectorial de documentos y los mensajes del usuario (PDFs, DOCX, TXT)."""
        if not document_context:
            return self._cap(
                "No encontré información relevante en los documentos indexados o en los mensajes del usuario. "
                "¿Podrías subir el PDF o documento que deseas consultar?"
            )
        prompt = (
            f"{document_context}\n\n"
            f"PREGUNTA DEL USUARIO: {user_query}\n\n"
            f"{LENGTH_INSTRUCTION}"
        )
        response = self._generate(prompt)
        return self._cap(response.text)

    def _answer_without_data_file(
        self, user_query: str, document_context: str, require_strict_data: bool = False
    ) -> str:
        """Respuesta cuando no hay archivo de datos ni documentos relevantes."""
        if document_context:
            return self._answer_document_only(user_query, document_context, require_strict_data)
        if require_strict_data:
            return self._cap(
                "El backend indica que hay archivos asociados a esta conversación, pero no detecté un CSV/Excel "
                "analizable ni contexto indexado de documentos para esta consulta. Sube un CSV o Excel, "
                "o reformula la pregunta para apoyarte en los documentos ya indexados."
            )
        prompt = user_query + "\n\n" + LENGTH_INSTRUCTION
        response = self._generate(prompt)
        return self._cap(response.text)

    def _extract_echarts_json(self, text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Separa el bloque ```echarts-json del texto y devuelve (texto_limpio, opción ECharts o None)."""
        pattern = r"```echarts-json\s*([\s\S]*?)\s*```"
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return text, None
        raw = m.group(1).strip()
        cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return cleaned, None
        if isinstance(obj, dict) and "echarts_option" in obj:
            inner = obj["echarts_option"]
            if isinstance(inner, dict):
                obj = inner
            else:
                return cleaned, None
        if not isinstance(obj, dict):
            return cleaned, None
        return cleaned, obj

    def _extract_echarts_from_stdout(self, stdout: str) -> Optional[Dict[str, Any]]:
        """
        Extrae el option ECharts del stdout del sandbox cuando el código generado
        siguió la Regla 14 e imprimió: ECHARTS_JSON_OUTPUT:<json>
        """
        if not stdout:
            return None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("ECHARTS_JSON_OUTPUT:"):
                raw = line[len("ECHARTS_JSON_OUTPUT:"):].strip()
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and obj:
                        return obj
                except (json.JSONDecodeError, ValueError):
                    pass
        return None

    def _request_echarts_option_dedicated(self, analysis_stdout: str) -> Optional[Dict[str, Any]]:
        """
        Segundo LLM call dedicado SOLO a generar el option ECharts.
        Se invoca únicamente cuando los intentos 0 y 1 no produjeron option.
        El prompt es intencional y corto para que el LLM no gaste tokens en narrativa.
        """
        # Truncar stdout para que el prompt no exceda el contexto del modelo
        _MAX_STDOUT = 3000
        stdout_snippet = analysis_stdout[:_MAX_STDOUT] if len(analysis_stdout) > _MAX_STDOUT else analysis_stdout
        prompt = (
            "Eres un generador de configuraciones Apache ECharts. Tu ÚNICA tarea es emitir un bloque JSON.\n\n"
            "Con base EXCLUSIVAMENTE en los siguientes resultados del análisis de datos, "
            "genera UN objeto JSON de configuración de Apache ECharts (bar chart) "
            "que represente el insight principal (distribución, ranking o tendencia más relevante).\n\n"
            f"RESULTADOS DEL ANÁLISIS:\n{stdout_snippet}\n\n"
            "RESPONDE ÚNICAMENTE con el bloque JSON, sin texto adicional, sin markdown de narrativa:\n"
            "```echarts-json\n"
            "{ \"title\": { \"text\": \"...\", \"left\": \"center\", \"textStyle\": { \"color\": \"#ffffff\" } },\n"
            "  \"tooltip\": { \"trigger\": \"axis\", \"axisPointer\": { \"type\": \"shadow\" } },\n"
            "  \"xAxis\": { \"type\": \"category\", \"data\": [...] },\n"
            "  \"yAxis\": { \"type\": \"value\", \"splitLine\": { \"lineStyle\": { \"color\": \"#333333\" } } },\n"
            "  \"series\": [{ \"name\": \"Registros\", \"type\": \"bar\", \"data\": [...], \"itemStyle\": { \"color\": \"#ff6d00\" } }] }\n"
            "```\n"
            "REGLAS: usa SOLO números de los resultados, no inventes valores. Si no hay datos suficientes, devuelve {}."
        )
        try:
            response = self._generate(prompt)
            _, opt = self._extract_echarts_json(response.text or "")
            if isinstance(opt, dict) and opt:
                return opt
        except Exception as e:
            print(f"DEBUG _request_echarts_option_dedicated falló: {e}")
        return None

    def _build_echarts_from_namespace(
        self, namespace: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback determinístico post-sandbox: compila un ECharts option desde los
        DataFrames que el código generado dejó en el namespace del sandbox.

        Estrategia:
          1. Busca DataFrames ya agregados (resumen, resultado, top, ranking…);
             si tienen columna categórica + numérica los serializa directamente.
          2. Si no, toma el DataFrame principal 'df' y lo agrupa internamente.
          3. Elige tipo de gráfica según cardinalidad y presencia de columna de fecha.
        Paleta corporativa: #ff6d00 (DEFAULT_BAR_COLOR de echarts_builder).
        """
        _DATE_KEYWORDS = (
            "fecha", "date", "mes", "month", "año", "year",
            "periodo", "period", "semana", "trimestre", "quarter",
        )
        _AGG_VAR_NAMES = (
            "resumen", "resultado", "summary", "result",
            "top", "ranking", "grouped", "agrupado",
            "ventas_por", "totales", "conteo",
        )

        def _has_date_hint(col: str) -> bool:
            return any(kw in str(col).lower() for kw in _DATE_KEYWORDS)

        def _best_cat(df: pd.DataFrame, exclude: Optional[str] = None) -> Optional[str]:
            for c in df.columns:
                if c == exclude:
                    continue
                if not pd.api.types.is_numeric_dtype(df[c]) and 2 <= df[c].nunique() <= 50:
                    return c
            return None

        def _best_num(df: pd.DataFrame, exclude: Optional[str] = None) -> Optional[str]:
            for c in df.columns:
                if c != exclude and pd.api.types.is_numeric_dtype(df[c]):
                    return c
            return None

        def _try_build(
            df: pd.DataFrame, aggregated: bool, tag: str
        ) -> Optional[Dict[str, Any]]:
            if not isinstance(df, pd.DataFrame) or df.empty or len(df) < 2:
                return None
            date_col = next((c for c in df.columns if _has_date_hint(c)), None)
            group_col = date_col or _best_cat(df)
            if group_col is None:
                return None
            num_col = _best_num(df, exclude=group_col)
            has_date = group_col == date_col
            nuniq = df[group_col].nunique()
            if has_date:
                chart_type, title_pfx = "line", "Evolución"
            elif nuniq <= 7:
                chart_type, title_pfx = "pie", "Distribución"
            elif nuniq > 15:
                chart_type, title_pfx = "horizontal_bar", "Ranking"
            else:
                chart_type, title_pfx = "bar", "Distribución"
            title = f"{title_pfx} por {group_col}"
            try:
                if aggregated:
                    return dataframe_to_echarts_option(
                        df, title=title, category_column=group_col, value_column=num_col
                    )
                return aggregate_and_build_option(
                    df,
                    group_col,
                    value_column=num_col,
                    agg="sum" if num_col else "count",
                    chart_type=chart_type,
                    title=title,
                )
            except Exception as exc:
                print(f"DEBUG _build_echarts_from_namespace({tag}): {exc}")
                return None

        # Paso 1 — DataFrames ya agregados (resultado de un groupby en el sandbox)
        for key in _AGG_VAR_NAMES:
            val = namespace.get(key)
            if isinstance(val, pd.DataFrame) and not val.empty and 2 <= len(val) <= 200:
                opt = _try_build(val, aggregated=True, tag=key)
                if opt:
                    return opt

        # Paso 2 — DataFrame principal 'df' (datos en bruto; se agrupa aquí)
        df_main: Optional[pd.DataFrame] = namespace.get("df")
        if not isinstance(df_main, pd.DataFrame) or df_main.empty:
            for v in namespace.values():
                if isinstance(v, pd.DataFrame) and not v.empty and len(v) >= 2:
                    df_main = v
                    break
        return _try_build(df_main, aggregated=False, tag="df")  # type: ignore[arg-type]

    def _build_read_instruction(self, clean_path: str, path_lower: str, csv_encoding: Optional[str]) -> str:
        enc_note = (
            f" Se detectó encoding '{csv_encoding}' en el muestreo." if csv_encoding and csv_encoding != "utf-8" else ""
        )
        return (
            f"Para cargar SIEMPRE usa: df = cargar_dataframe_limpio(). "
            f"Esa función ya apunta a '{clean_path}', aplica heurística de encabezado (DIAN/RIPS), "
            f"expansión de delimitadores complejos ('|',';') y limpieza silenciosa de nulos.{enc_note}"
        )

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
        require_strict_data: bool = False,
    ) -> str:
        strict_prefix = ""
        if require_strict_data:
            strict_prefix = (
                "MODO ESTRICTO (confirmado por el backend): Esta conversación tiene archivos del usuario "
                "en su carpeta de datos. Está PROHIBIDO inventar cifras, tablas o series que no provengan "
                "del archivo indicado abajo o de contexto_documentos. Si no alcanza, detente y explica qué falta y pregunta al usuario; "
                "no rellenes con datos supuestos.\n\n"
            )
        system = strict_prefix + (
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
            "los aplica el sistema; no los codifiques en Python.\n"
            "13. REGLAS DE INGESTA OBLIGATORIAS (NO negociables):\n"
            "   - No asumas encabezado en fila 0: usa SIEMPRE `df = cargar_dataframe_limpio()`.\n"
            "   - Si el origen viene concatenado por '|' o ';', la expansión ya ocurre en la función de carga.\n"
            "   - La limpieza de NaN debe ser silenciosa: NO pidas aclaraciones al usuario por esto.\n"
            "14. REGLA DE DASHBOARD ECHARTS (OBLIGATORIA cuando hay DataFrame):\n"
            "   Al final del script, SIEMPRE genera el option ECharts del insight más representativo. "
            "   Tienes AUTONOMÍA TOTAL para elegir el tipo de visualización adecuado al dato. "
            "   Helpers disponibles ya inyectados (NO los importes, úsalos directo):\n"
            "     • aggregate_and_build_option(df, col, agg='count'|'sum'|'mean', value_column=..., chart_type='bar'|'line'|'pie'|'horizontal_bar', title='...')\n"
            "     • build_line_option(categories, values, title='...', series_name='...')\n"
            "     • build_pie_option(categories, values, title='...')\n"
            "     • build_horizontal_bar_option(categories, values, title='...')\n"
            "     • build_scatter_option(xs, ys, title='...', x_label='...', y_label='...')\n"
            "     • build_heatmap_option(matrix, x_labels=..., y_labels=..., title='...')\n"
            "     • correlation_heatmap_from_df(df, title='Matriz de Correlación') ← usa esto si el insight es de correlación\n"
            "     • build_stacked_bar_option(categories, {nombre: valores, ...}, title='...')\n"
            "   GUÍA RÁPIDA DE ELECCIÓN (decide en función del DATO, no por defecto barras):\n"
            "     - Serie temporal o tendencia (fechas/meses/años) → build_line_option o aggregate_and_build_option(..., chart_type='line').\n"
            "     - Proporción / share de mercado / composición (≤10 categorías) → build_pie_option o chart_type='pie'.\n"
            "     - Ranking con etiquetas largas o muchas categorías → build_horizontal_bar_option o chart_type='horizontal_bar'.\n"
            "     - Correlación entre variables numéricas → correlation_heatmap_from_df(df).\n"
            "     - Dos variables continuas → build_scatter_option.\n"
            "     - Composición por categoría con sub-segmentos → build_stacked_bar_option.\n"
            "     - Conteo simple por categoría sin matiz temporal → bar (default) está bien.\n"
            "   FORMATO DE SALIDA OBLIGATORIO (esta es la línea que alimenta el visor):\n"
            "      `print('ECHARTS_JSON_OUTPUT:' + json.dumps(_ec_opt))`\n"
            "   Donde `_ec_opt` es el dict devuelto por el helper elegido. Si tu primer intento devuelve None, "
            "   prueba otro helper o cambia la columna; NO te rindas en silencio. NO uses matplotlib para esto.\n"
            "   PROHIBIDO siempre usar el mismo helper: cada análisis distinto debe justificar su tipo de gráfica."
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
        user_query: str,
        chat_id: Optional[int],
        clean_path: str,
        csv_encoding: Optional[str],
        document_context: str,
        report_pdf_path: str,
        report_excel_path: str,
        plot_filename: str,
        report_config: Optional[ReportConfig] = None,
        generate_echarts: bool = False,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
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
            "json": json,
            "contexto_documentos": document_context or "",
            "generar_reporte_pdf": generar_pdf,
            "generar_reporte_excel_avanzado": generar_excel,
            "cargar_dataframe_limpio": functools.partial(
                load_structured_dataframe,
                clean_path,
                csv_encoding=csv_encoding,
                chat_id=chat_id,
            ),
            # ECharts helpers: disponibles en el sandbox para que el LLM elija el tipo más adecuado.
            "aggregate_and_build_option": aggregate_and_build_option,
            "dataframe_to_echarts_option": dataframe_to_echarts_option,
            "build_bar_option": build_bar_option,
            "build_line_option": build_line_option,
            "build_pie_option": build_pie_option,
            "build_horizontal_bar_option": build_horizontal_bar_option,
            "build_scatter_option": build_scatter_option,
            "build_heatmap_option": build_heatmap_option,
            "build_stacked_bar_option": build_stacked_bar_option,
            "correlation_heatmap_from_df": correlation_heatmap_from_df,
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

        # Intento 0: extraer echarts_option directamente del stdout del sandbox (Regla 14).
        # El código generado imprime 'ECHARTS_JSON_OUTPUT:<json>' si aggregate_and_build_option tuvo éxito.
        opt: Optional[Dict[str, Any]] = None
        if generate_echarts:
            opt = self._extract_echarts_from_stdout(resultados)

        prompt_final = (
            f"El código se ejecutó con éxito. Resultados técnicos del análisis de datos:\n{resultados}\n\n"
            f"{narrative_contract}"
            "Responde como Analista Senior de InsightFlow. No menciones el código, solo conclusiones y "
            f"hallazgos en lenguaje natural.{cross_reference} {LENGTH_INSTRUCTION}"
        )
        response = self._generate(prompt_final)
        text = response.text

        # Intento 1: si el stdout no trajo el option, intentar extraerlo del texto narrativo del LLM
        # (el LLM puede incluir un bloque ```echarts-json``` aunque no se le pida explícitamente).
        if generate_echarts and opt is None:
            text, opt = self._extract_echarts_json(text)

        # Intento 1.5 — fallback determinístico con echarts_builder.
        # Inspecciona el namespace post-safe_exec: agrupa el DataFrame transaccional y
        # compila el option directamente con aggregate_and_build_option / dataframe_to_echarts_option.
        # Más rápido y fiable que el segundo LLM call cuando las columnas son claras.
        if generate_echarts and opt is None:
            opt = self._build_echarts_from_namespace(namespace)

        # Intento 2: si todavía no hay option, hacer un segundo LLM call corto y enfocado SOLO en ECharts.
        # Esto evita el conflicto con LENGTH_INSTRUCTION que impide al LLM emitir el bloque en el call principal.
        if generate_echarts and opt is None:
            opt = self._request_echarts_option_dedicated(resultados)

        sidecar_meta = _load_sidecar_metadata_context(clean_path)
        compliance_context = document_context or ""
        if sidecar_meta:
            compliance_context = (
                f"{compliance_context}\n\n{sidecar_meta}" if compliance_context else sidecar_meta
            )

        compliance_block = self._compliance_agent.build_diagnostic(
            user_query=user_query,
            analysis_stdout=resultados,
            document_context=compliance_context,
        )
        if compliance_block:
            text = f"{text.strip()}\n\n{compliance_block.strip()}"

        # ── Re-render del PDF con la narrativa REAL ya generada ─────────────────
        # El LLM generó el PDF pasando `contexto_documentos` (vacío o solo docs
        # indexados) como texto. Ahora sobrescribimos con la narrativa completa:
        # consulta + análisis + compliance + gráfica matplotlib.
        try:
            # Resolver la ruta de la gráfica: el sandbox la creó en data/{chat_id}/
            chart_abs = None
            if ruta_img:
                _check = os.path.join(os.path.dirname(os.path.abspath(clean_path)), os.path.basename(ruta_img))
                if os.path.isfile(_check):
                    chart_abs = _check
                elif os.path.isfile(ruta_img):
                    chart_abs = os.path.abspath(ruta_img)
            charts_for_pdf: List[str] = [chart_abs] if chart_abs else []

            narrativa_para_pdf = (
                f"Consulta del usuario: {user_query}\n\n"
                f"{text.strip()}"
            )

            # Si el LLM generó un PDF, sobreescribirlo con la versión premium.
            # Si NO generó uno, crearlo igualmente para que el usuario lo reciba.
            pdf_output = self._pending_pdf_report_path
            if not pdf_output:
                pdf_output = report_pdf_path
            generar_reporte_premium_pdf(
                narrativa_para_pdf,
                ruta_salida=pdf_output,
                rutas_graficas=charts_for_pdf or None,
                report_config=report_config,
            )
            self._pending_pdf_report_path = pdf_output
            print(f"DEBUG: PDF premium re-generado en {pdf_output} ({len(narrativa_para_pdf)} chars de narrativa, {len(charts_for_pdf)} gráficas)")
        except Exception as e:
            print(f"DEBUG: re-render premium PDF falló (se conserva el original): {e}")

        return self._cap(text), opt

    # ── Punto de entrada principal ───────────────────────────────────────

    async def analyze_data(
        self,
        user_query: str,
        local_file_path: Optional[str] = None,
        user_data_folder: Optional[str] = None,
        chat_id: Optional[int] = None,
        report_config: Optional[ReportConfig] = None,
        require_strict_data: bool = False,
        generate_echarts: bool = False,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
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
                return (
                    self._answer_document_only(
                        user_query, document_context, require_strict_data
                    ),
                    None,
                )
            return (
                self._answer_without_data_file(
                    user_query, document_context, require_strict_data
                ),
                None,
            )

        # Archivo de datos (CSV/Excel) presente → generar código de análisis
        try:
            df_sample, csv_encoding = _read_schema_sample(data_file_path)
            schema_info = f"Columnas: {list(df_sample.columns)}\nMuestra: {df_sample.to_dict('records')}"
        except Exception as e:
            return f"Error al leer la estructura del archivo local: {e}", None

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
            require_strict_data=require_strict_data,
        )

        try:
            response = self._generate(prompt)
            respuesta_texto = response.text
            codigo_python = self._sanitize_code(self._extraer_codigo(respuesta_texto))
        except Exception as e:
            return f"Error de comunicación con el modelo de análisis: {str(e)}", None

        if not self._looks_like_python_code(codigo_python):
            return self._cap(respuesta_texto), None

        try:
            return self._run_code_and_summarize(
                codigo_python,
                user_query,
                chat_id,
                clean_path,
                csv_encoding,
                document_context,
                report_pdf_path,
                report_excel_path,
                plot_filename,
                report_config=report_config,
                generate_echarts=generate_echarts,
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
                        user_query,
                        chat_id,
                        clean_path,
                        csv_encoding,
                        document_context,
                        report_pdf_path,
                        report_excel_path,
                        plot_filename,
                        report_config=report_config,
                        generate_echarts=generate_echarts,
                    )
            except Exception as e2:
                print(f"Error en reintento de corrección: {e2}")
            return (
                self._cap(
                    f"Encontré un problema al analizar el archivo: {e}. "
                    "Por favor verifica que el archivo CSV esté bien formado o intenta con otra pregunta."
                ),
                None,
            )

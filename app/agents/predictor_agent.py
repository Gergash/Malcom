"""
PredictorAgent: responde preguntas de negocio (ej. "¿Cuánto stock comprar esta semana?")
usando solo los archivos de la carpeta del usuario (data/{chat_id}/): CSV, XLSX, etc.
Cada usuario tiene su carpeta; al volver al chat se usa esa misma carpeta.
"""
import google.generativeai as genai
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

# Extensiones que podemos usar para resumen de demanda (datos tabulares)
DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _get_latest_data_file(user_data_folder: str):
    """
    Devuelve la ruta del archivo más reciente (por modificación) en la carpeta del usuario
    que sea CSV o XLSX. Si no hay, None.
    """
    if not user_data_folder or not os.path.isdir(user_data_folder):
        return None
    candidates = []
    for name in os.listdir(user_data_folder):
        if name.lower().endswith(DATA_EXTENSIONS):
            path = os.path.join(user_data_folder, name)
            try:
                mtime = os.path.getmtime(path)
                candidates.append((mtime, path))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _read_table(path: str) -> pd.DataFrame:
    """Carga CSV o XLSX en un DataFrame (muestra limitada para no saturar)."""
    path_lower = path.lower()
    try:
        if path_lower.endswith(".csv"):
            return pd.read_csv(path, nrows=50000)
        if path_lower.endswith((".xlsx", ".xls")):
            return pd.read_excel(path, nrows=50000)
    except Exception as e:
        return pd.DataFrame()
    return pd.DataFrame()


def _demand_summary_from_df(df: pd.DataFrame, source: str) -> str:
    """Construye un resumen de demanda a partir de un DataFrame (columna numérica tipo cantidad)."""
    if df.empty or len(df) == 0:
        return f"El archivo '{source}' no tiene datos utilizables."
    # Buscar columna de cantidad/demanda
    qty_candidates = [
        c for c in df.columns
        if any(x in str(c).lower() for x in ("qty", "quantity", "value", "amount", "demand", "units", "venta", "cantidad", "total", "suma"))
    ]
    if not qty_candidates:
        nums = df.select_dtypes(include=["number"]).columns.tolist()
        qty_col = nums[-1] if nums else df.columns[-1]
    else:
        qty_col = qty_candidates[0]
    series = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    total = series.sum()
    n_rows = len(df)
    avg = total / max(1, n_rows)
    return (
        f"Archivo: {source}. Filas: {n_rows}. Columna usada: '{qty_col}'. "
        f"Total: {total:.1f}. Promedio por fila: {avg:.1f}."
    )


def get_demand_summary(
    local_file_path: str = None,
    user_data_folder: str = None,
) -> str:
    """
    Genera un resumen de demanda para el predictor.
    - Si viene local_file_path (archivo concreto), se usa ese archivo.
    - Si no, se usa user_data_folder (data/{chat_id}): se toma el archivo de datos
      más reciente (CSV/XLSX) en esa carpeta.
    No se usa TTCA ni ninguna carpeta global; solo la carpeta del usuario.
    """
    path = None
    if local_file_path and os.path.isfile(local_file_path):
        path = local_file_path
    elif user_data_folder:
        path = _get_latest_data_file(user_data_folder)
    if not path:
        return (
            "No hay archivos de datos para este usuario. "
            "Sube un CSV o Excel a la conversación para que pueda darte recomendaciones."
        )
    df = _read_table(path)
    return _demand_summary_from_df(df, os.path.basename(path))


try:
    from app.agents.model_manager import get_primary_gemini_model
except ModuleNotFoundError:
    from agents.model_manager import get_primary_gemini_model


class PredictorAgent:
    """
    Responde preguntas de negocio usando solo la información de la carpeta del usuario
    (data/{chat_id}/). Cuando el usuario vuelve al chat, se usa esa misma carpeta.
    """

    def __init__(self):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.identity = (
            "Eres el predictor de negocio de InsightFlow.\n"
            "Tu propósito es responder preguntas de negocio con recomendaciones concretas "
            "(por ejemplo: cuánto stock comprar, pronósticos, cantidades a pedir).\n"
            "Siempre das un número o rango cuando sea posible y una explicación breve.\n"
            "Te presentas como el Predictor de InsightFlow."
        )
        self.model = genai.GenerativeModel(
            model_name=get_primary_gemini_model(),
            system_instruction=self.identity,
        )

    def answer_business_question(
        self,
        user_query: str,
        local_file_path: str = None,
        user_data_folder: str = None,
    ) -> str:
        """
        Responde usando los datos de la carpeta del usuario (data/{chat_id}/).
        - local_file_path: archivo que el usuario acaba de subir (opcional).
        - user_data_folder: carpeta del usuario (data/{chat_id}) para buscar archivos
          si no hay archivo concreto o para futuras consultas en la misma sesión.
        """
        summary = get_demand_summary(
            local_file_path=local_file_path,
            user_data_folder=user_data_folder,
        )
        prompt = (
            "RESUMEN DE DEMANDA / DATOS DEL USUARIO:\n"
            f"{summary}\n\n"
            "PREGUNTA DEL USUARIO:\n"
            f"{user_query}\n\n"
            "Responde en lenguaje natural, con una recomendación concreta (número o rango) "
            "y una explicación breve basada en los datos."
        )
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error al generar la recomendación: {str(e)}"

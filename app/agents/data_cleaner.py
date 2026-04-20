"""
data_cleaner.py: Limpieza heurística automática de archivos de datos gubernamentales
(DIAN, comercio exterior, reportes oficiales colombianos).

Implementa tres mejoras silenciosas:
  1. Escáner de heurística de cabeceras   — detecta la fila real del header sin preguntar.
  2. Tokenización de delimitadores complejos — expande columnas con separador '|'.
  3. Loop de autocorrección silenciosa    — reintenta si el DataFrame es incoherente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

# ── Vocabulario de cabeceras de comercio exterior / reportes DIAN ──────────────
_HEADER_KEYWORDS: frozenset = frozenset({
    "fob", "cif", "aduana", "arancel", "nandina", "partida", "importacion",
    "importación", "exportacion", "exportación", "origen", "destino", "pais",
    "país", "declaracion", "declaración", "dian", "subpartida", "descripcion",
    "descripción", "factura", "valor", "peso", "unidades", "cantidad",
    "proveedor", "empresa", "nit", "razon", "razón", "social", "modalidad",
    "regimen", "régimen", "puerto", "periodo", "período", "año", "mes",
    "fecha", "numero", "número", "código", "codigo", "total", "tipo",
    "nombre", "ciudad", "departamento", "municipio", "clase", "identificacion",
    "identificación", "producto", "item", "ítem", "referencia",
})

_PIPE_DENSITY_THRESHOLD = 0.60   # ≥ 60 % de celdas con "|" → columna pipe
_NAN_THRESHOLD = 0.90            # ≥ 90 % NaN → DataFrame incoherente
_MIN_COLUMNS = 3                 # < 3 columnas → DataFrame incoherente
_MAX_SCAN_ROWS = 20              # filas a escanear para detectar el header
_SAMPLE_ROWS = 5                 # filas de muestra que devuelve smart_read_schema


@dataclass
class ReadResult:
    df: pd.DataFrame
    encoding: str
    header_row: int            # índice de fila real del header (parámetro pandas header=)
    pipe_columns: List[str]    # columnas originales que contenían separador "|"
    was_cleaned: bool          # True si se aplicó alguna corrección automática


# ── Helpers de detección ──────────────────────────────────────────────────────

def _count_keywords(row: pd.Series) -> int:
    """Cuenta cuántas palabras clave de cabecera aparecen en una fila."""
    count = 0
    for val in row:
        if pd.isna(val):
            continue
        text = str(val).lower()
        tokens = re.split(r"[\s|,;_\-\.\/\\()\[\]]+", text)
        for tok in tokens:
            if tok in _HEADER_KEYWORDS:
                count += 1
    return count


def _find_best_header_row(raw: pd.DataFrame) -> int:
    """
    Devuelve el índice (0-based) de la fila con más palabras clave de cabecera.
    Solo desplaza si la mejora es significativa: ≥ 2 keywords Y supera claramente a la fila 0.
    """
    limit = min(_MAX_SCAN_ROWS, len(raw))
    scores = [_count_keywords(raw.iloc[i]) for i in range(limit)]
    if not scores:
        return 0
    row0_score = scores[0]
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_idx]
    if best_idx > 0 and best_score >= 2 and best_score > row0_score:
        return best_idx
    return 0


def _is_coherent(df: pd.DataFrame) -> bool:
    """True si el DataFrame tiene ≥ MIN_COLUMNS columnas y < NAN_THRESHOLD de valores nulos."""
    if len(df.columns) < _MIN_COLUMNS:
        return False
    return df.isnull().values.mean() < _NAN_THRESHOLD


def _detect_pipe_columns(df: pd.DataFrame) -> List[str]:
    """Lista de columnas donde ≥ 60 % de los valores no-nulos contienen '|'."""
    result = []
    for col in df.columns:
        non_null = df[col].dropna()
        if len(non_null) == 0:
            continue
        density = non_null.astype(str).str.contains(r"\|", regex=True).mean()
        if density >= _PIPE_DENSITY_THRESHOLD:
            result.append(str(col))
    return result


def _expand_pipe_columns(df: pd.DataFrame, pipe_cols: List[str]) -> pd.DataFrame:
    """
    Expande cada columna pipe en múltiples columnas limpias, reemplazando la original.
    Ej: columna "datos" con "10|20|30" → "datos_p0"=10, "datos_p1"=20, "datos_p2"=30.
    """
    result = df.copy()
    for col in pipe_cols:
        if col not in result.columns:
            continue
        expanded = result[col].astype(str).str.split(r"\|", expand=True)
        expanded = expanded.apply(lambda s: s.str.strip() if s.dtype == object else s)
        expanded.columns = [f"{col}_p{i}" for i in range(len(expanded.columns))]
        idx = result.columns.get_loc(col)
        result = pd.concat(
            [result.iloc[:, :idx], expanded, result.iloc[:, idx + 1:]],
            axis=1,
        )
    return result


# ── Función principal ─────────────────────────────────────────────────────────

def smart_read_schema(path: str) -> ReadResult:
    """
    Lee un CSV/Excel aplicando tres capas de limpieza heurística automática:

    1. Lee el archivo crudo (sin header) para escanear hasta MAX_SCAN_ROWS filas
       y encontrar la fila con mayor densidad de palabras clave de cabecera.

    2. Carga el archivo con ese header_row. Si el resultado es incoherente
       (< 3 columnas o > 90 % NaN), reintenta con header=0 (loop silencioso).

    3. Detecta columnas con ≥ 60 % de celdas con '|' y las expande
       en columnas _p0, _p1, _p2... antes de devolverlas al agente.

    Retorna ReadResult con el DataFrame limpio, el encoding usado, la fila
    real del header, las columnas expandidas y si se aplicó alguna corrección.
    """
    path_lower = path.lower()
    is_excel = path_lower.endswith((".xlsx", ".xls"))

    # ── Paso 1: lectura cruda para escanear filas ─────────────────────────
    encoding = "latin-1"
    raw: Optional[pd.DataFrame] = None

    if is_excel:
        try:
            raw = pd.read_excel(path, nrows=_MAX_SCAN_ROWS, header=None)
        except Exception:
            pass
    else:
        for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
            try:
                raw = pd.read_csv(
                    path,
                    nrows=_MAX_SCAN_ROWS,
                    header=None,
                    encoding=enc,
                    sep=None,
                    engine="python",
                    on_bad_lines="skip",
                )
                encoding = enc
                break
            except Exception:
                continue

    if raw is None or raw.empty:
        # Fallback total: lectura estándar sin heurística
        try:
            df = pd.read_excel(path, nrows=_SAMPLE_ROWS) if is_excel else pd.read_csv(path, nrows=_SAMPLE_ROWS, encoding="latin-1")
        except Exception:
            df = pd.DataFrame()
        return ReadResult(df=df, encoding="latin-1", header_row=0, pipe_columns=[], was_cleaned=False)

    # ── Paso 2: detectar fila de header óptima ────────────────────────────
    best_header = _find_best_header_row(raw)

    # ── Paso 3: cargar con header detectado — loop de autocorrección ──────
    # Prueba primero el header óptimo; si el DataFrame es incoherente, cae al 0
    candidate_headers = list(dict.fromkeys([best_header, 0]))
    df: Optional[pd.DataFrame] = None
    final_header = 0

    for hrow in candidate_headers:
        try:
            if is_excel:
                df_try = pd.read_excel(path, nrows=_SAMPLE_ROWS, header=hrow)
            else:
                df_try = pd.read_csv(
                    path,
                    nrows=_SAMPLE_ROWS,
                    header=hrow,
                    encoding=encoding,
                    sep=None,
                    engine="python",
                    on_bad_lines="skip",
                )
            if _is_coherent(df_try):
                df = df_try
                final_header = hrow
                break
        except Exception:
            continue

    if df is None:
        # Último recurso: lectura básica sin heurística
        try:
            df = pd.read_excel(path, nrows=_SAMPLE_ROWS) if is_excel else pd.read_csv(path, nrows=_SAMPLE_ROWS, encoding=encoding)
        except Exception:
            df = pd.DataFrame()
        final_header = 0

    # ── Paso 4: detectar y expandir columnas con separador '|' ───────────
    pipe_cols = _detect_pipe_columns(df)
    if pipe_cols:
        df = _expand_pipe_columns(df, pipe_cols)

    was_cleaned = final_header != 0 or bool(pipe_cols)
    return ReadResult(
        df=df,
        encoding=encoding,
        header_row=final_header,
        pipe_columns=pipe_cols,
        was_cleaned=was_cleaned,
    )

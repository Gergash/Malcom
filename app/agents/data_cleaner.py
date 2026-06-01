"""
data_cleaner.py: limpieza determinista avanzada para datasets corporativos.

Pipeline (pre-LLM):
1) Extracción de metadatos sidecar (.meta.json)
2) Detección de header + expansión de delimitadores complejos
3) Escudo de tipados locales (NIT/cédula + monedas híbridas)
4) Armonización canónica (fuzzy matching)
5) Cuarentena de excepciones (coerce + imputación por contexto)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

try:
    from rapidfuzz import process as rf_process  # type: ignore
except Exception:  # pragma: no cover - fallback si rapidfuzz no está instalado
    rf_process = None

_HEADER_KEYWORDS: frozenset[str] = frozenset(
    {
        "fob",
        "cif",
        "aduana",
        "arancel",
        "nandina",
        "partida",
        "importacion",
        "importación",
        "exportacion",
        "exportación",
        "origen",
        "destino",
        "pais",
        "país",
        "declaracion",
        "declaración",
        "dian",
        "subpartida",
        "descripcion",
        "descripción",
        "factura",
        "valor",
        "peso",
        "unidades",
        "cantidad",
        "proveedor",
        "empresa",
        "nit",
        "razon",
        "razón",
        "social",
        "modalidad",
        "regimen",
        "régimen",
        "puerto",
        "periodo",
        "período",
        "año",
        "mes",
        "fecha",
        "numero",
        "número",
        "código",
        "codigo",
        "total",
        "tipo",
        "nombre",
        "ciudad",
        "departamento",
        "municipio",
        "clase",
        "identificacion",
        "identificación",
        "producto",
        "item",
        "ítem",
        "referencia",
    }
)

_MAX_SCAN_ROWS = 24
_PIPE_DENSITY_THRESHOLD = 0.60
_ID_DENSITY_THRESHOLD = 0.70
_FUZZY_THRESHOLD = 85

_ID_COL_HINTS = ("nit", "cédula", "cedula", "identificacion", "identificación", "documento")
_COP_COL_HINTS = ("cop", "peso", "pesos", "costo", "flete", "seguro", "valor", "monto", "importe", "total")
_USD_COL_HINTS = ("usd", "dolar", "dólar", "us$", "u$s", "dollars")
_NUMERIC_CRITICAL_HINTS = ("valor", "cif", "fob", "monto", "importe", "precio", "total", "flete", "seguro")
_ACCUMULATIVE_HINTS = ("flete", "seguro", "gasto", "costo", "cargo", "impuesto")
_DATE_HINTS = ("fecha", "presentacion", "presentación", "declaracion", "declaración")

_CANONICAL_CATALOG: Dict[str, List[str]] = {
    "ciudades": [
        "BOGOTA",
        "MEDELLIN",
        "CALI",
        "BARRANQUILLA",
        "CARTAGENA",
        "BUCARAMANGA",
        "PEREIRA",
    ],
    "departamentos": [
        "CUNDINAMARCA",
        "ANTIOQUIA",
        "VALLE DEL CAUCA",
        "ATLANTICO",
        "BOLIVAR",
        "SANTANDER",
    ],
    "puertos": [
        "PUERTO DE CARTAGENA",
        "PUERTO DE BUENAVENTURA",
        "PUERTO DE BARRANQUILLA",
        "PUERTO DE SANTA MARTA",
    ],
    "aduanas": [
        "ADUANA DE EL DORADO",
        "ADUANA DE BUENAVENTURA",
        "ADUANA DE CARTAGENA",
        "ADUANA DE BARRANQUILLA",
        "ADUANA DE MEDELLIN",
    ],
    "bancos": [
        "BANCOLOMBIA",
        "BANCO DE BOGOTA",
        "BANCO DAVIVIENDA",
        "BANCO BBVA COLOMBIA",
        "BANCO POPULAR",
    ],
}


@dataclass
class ReadResult:
    df: pd.DataFrame
    encoding: str
    header_row: int
    pipe_columns: List[str]
    was_cleaned: bool
    metadata: Dict[str, Any]
    metadata_path: Optional[str] = None


def _norm_text(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip())


def _count_keywords(row: Iterable[Any]) -> int:
    score = 0
    for val in row:
        txt = _norm_text(val).lower()
        if not txt or txt in {"nan", "none"}:
            continue
        tokens = re.split(r"[\s|,;_\-\.\/\\()\[\]]+", txt)
        score += sum(1 for tok in tokens if tok in _HEADER_KEYWORDS)
    return score


def _find_best_header_row(raw: pd.DataFrame) -> int:
    limit = min(_MAX_SCAN_ROWS, len(raw))
    if limit <= 0:
        return 0
    scores = [_count_keywords(raw.iloc[i].tolist()) for i in range(limit)]
    row0 = scores[0] if scores else 0
    best_idx = max(range(len(scores)), key=lambda i: scores[i]) if scores else 0
    best = scores[best_idx] if scores else 0
    return best_idx if best_idx > 0 and best >= 2 and best > row0 else 0


def _dedupe_headers(headers: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for idx, h in enumerate(headers):
        base = _norm_text(h) or f"col_{idx + 1}"
        if base.lower() in {"nan", "none"}:
            base = f"col_{idx + 1}"
        if base not in seen:
            seen[base] = 1
            out.append(base)
        else:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")
    return out


def _read_raw(path: str, csv_encoding: Optional[str]) -> Tuple[pd.DataFrame, str]:
    is_excel = path.lower().endswith((".xlsx", ".xls"))
    if is_excel:
        return pd.read_excel(path, header=None, dtype=str), "utf-8"

    encodings = [e for e in [csv_encoding, "utf-8", "latin-1", "cp1252", "iso-8859-1"] if e]
    for enc in encodings:
        try:
            return pd.read_csv(path, header=None, dtype=str, sep=None, engine="python", encoding=enc), enc
        except Exception:
            continue
    return pd.read_csv(path, header=None, dtype=str, engine="python", encoding="latin-1"), "latin-1"


def _detect_dense_single_col(df: pd.DataFrame, sep: str) -> bool:
    if df.empty or df.shape[1] != 1:
        return False
    col = df.iloc[:, 0].astype(str)
    return float(col.str.contains(re.escape(sep), regex=True, na=False).mean()) >= _PIPE_DENSITY_THRESHOLD


def _expand_delimiters(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    if df.empty:
        return df, []
    original_cols: List[str] = []
    out = df.copy()
    for col in list(out.columns):
        series = out[col].astype(str)
        for sep in ("|", ";"):
            density = float(series.str.contains(re.escape(sep), regex=True, na=False).mean())
            if density < _PIPE_DENSITY_THRESHOLD:
                continue
            expanded = series.str.split(re.escape(sep), expand=True)
            expanded = expanded.apply(lambda s: s.str.strip() if s.dtype == object else s)
            expanded.columns = [f"{col}_p{i}" for i in range(expanded.shape[1])]
            idx = out.columns.get_loc(col)
            out = pd.concat([out.iloc[:, :idx], expanded, out.iloc[:, idx + 1 :]], axis=1)
            original_cols.append(str(col))
            break
    return out, original_cols


def _strip_id_like_token(value: Any) -> str:
    txt = _norm_text(value)
    if not txt:
        return ""
    txt = txt.replace(".", "").replace(",", "").replace(" ", "")
    txt = re.sub(r"-\w+$", "", txt)
    m = re.search(r"(\d{8,10})", txt)
    return m.group(1) if m else txt


def _looks_like_id_series(series: pd.Series) -> bool:
    non_null = series.dropna().astype(str).map(_norm_text)
    if non_null.empty:
        return False
    matches = non_null.str.replace(r"[.,\s]", "", regex=True).str.contains(r"^\d{8,10}(-\w+)?$")
    return float(matches.mean()) >= _ID_DENSITY_THRESHOLD


def _normalize_cop_number(value: Any) -> float:
    s = _norm_text(value)
    if not s:
        return float("nan")
    s = re.sub(r"[^0-9,.\-]", "", s)
    s = s.replace(".", "").replace(",", ".")
    return float(s) if s not in {"", "-", ".", ","} else float("nan")


def _normalize_usd_number(value: Any) -> float:
    s = _norm_text(value)
    if not s:
        return float("nan")
    s = re.sub(r"[^0-9,.\-]", "", s)
    s = s.replace(",", "")
    return float(s) if s not in {"", "-", ".", ","} else float("nan")


def _sanitize_local_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    protected_id_cols: set[str] = set()

    for col in out.columns:
        cname = str(col).lower()
        if any(h in cname for h in _ID_COL_HINTS) or _looks_like_id_series(out[col]):
            out[col] = out[col].map(_strip_id_like_token).astype("string")
            protected_id_cols.add(str(col))

    for col in out.columns:
        c = str(col)
        cname = c.lower()
        if c in protected_id_cols:
            continue
        series = out[c]
        if any(k in cname for k in _USD_COL_HINTS):
            out[c] = series.map(_normalize_usd_number)
        elif any(k in cname for k in _COP_COL_HINTS):
            out[c] = series.map(_normalize_cop_number)
    return out


def _best_match(value: str, choices: List[str]) -> Tuple[str, int]:
    val = value.upper().strip()
    if not val:
        return "", 0
    if rf_process is not None:
        m = rf_process.extractOne(val, choices)
        if not m:
            return "", 0
        return str(m[0]), int(m[1])
    best_term = ""
    best_score = 0
    for term in choices:
        score = int(100 * SequenceMatcher(None, val, term).ratio())
        if score > best_score:
            best_score = score
            best_term = term
    return best_term, best_score


def _column_catalog(col_name: str) -> Optional[List[str]]:
    name = col_name.lower()
    if any(k in name for k in ("ciudad", "municipio")):
        return _CANONICAL_CATALOG["ciudades"]
    if "departamento" in name:
        return _CANONICAL_CATALOG["departamentos"]
    if any(k in name for k in ("puerto", "zona franca", "terminal")):
        return _CANONICAL_CATALOG["puertos"]
    if "aduana" in name:
        return _CANONICAL_CATALOG["aduanas"]
    if any(k in name for k in ("banco", "entidad financiera")):
        return _CANONICAL_CATALOG["bancos"]
    return None


def _harmonize_categorical(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        catalog = _column_catalog(str(col))
        if not catalog:
            continue
        s = out[col].astype("string")
        uniques = [u for u in s.dropna().unique().tolist() if _norm_text(u)]
        mapper: Dict[str, str] = {}
        for raw_val in uniques:
            term, score = _best_match(str(raw_val), catalog)
            if score >= _FUZZY_THRESHOLD and term:
                mapper[str(raw_val)] = term
        if mapper:
            out[col] = s.replace(mapper)
    return out


def _coerce_numeric_quarantine(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        cname = str(col).lower()
        s = out[col]

        if any(k in cname for k in _DATE_HINTS):
            dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
            out[col] = dt.ffill()
            continue

        if not any(k in cname for k in _NUMERIC_CRITICAL_HINTS):
            continue

        numeric = pd.to_numeric(s, errors="coerce")
        if numeric.notna().mean() < 0.35:
            continue
        if any(k in cname for k in _ACCUMULATIVE_HINTS):
            out[col] = numeric.fillna(0.0)
        else:
            out[col] = numeric.ffill().fillna(0.0)
    return out


def _rows_to_metadata_context(raw: pd.DataFrame, header_row: int) -> str:
    if raw.empty or header_row <= 0:
        return ""
    top = raw.iloc[:header_row].fillna("").astype(str)
    lines: List[str] = []
    for _, row in top.iterrows():
        txt = " | ".join([_norm_text(v) for v in row.tolist() if _norm_text(v)])
        if txt:
            lines.append(txt)
    return "\n".join(lines[:20]).strip()


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    txt = (text or "").strip()
    if not txt:
        return {}
    # intenta bloque JSON puro o entre markdown fences
    txt = re.sub(r"^```json\s*|\s*```$", "", txt, flags=re.IGNORECASE)
    m = re.search(r"\{[\s\S]*\}", txt)
    candidate = m.group(0) if m else txt
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _extract_metadata_with_ollama(metadata_text: str) -> Dict[str, Any]:
    if not metadata_text:
        return {}
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    timeout = max(20, int(os.getenv("OLLAMA_TIMEOUT_SEC", "300")))

    prompt = (
        "Extrae metadata legal/administrativa del siguiente encabezado tabular. "
        "Devuelve solo JSON válido con esta forma exacta:\n"
        '{"document_metadata":{"fuente":"","regimen":"","periodo_inicio":"","periodo_fin":"","nit_declarante":""}}\n'
        "Si algún dato no existe, usa string vacío.\n\n"
        f"ENCABEZADO:\n{metadata_text}"
    )
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.0, "num_predict": 300}}
    try:
        resp = requests.post(f"{base}/api/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        raw_text = str(resp.json().get("response", "")).strip()
        parsed = _extract_json_from_text(raw_text)
        if isinstance(parsed.get("document_metadata"), dict):
            return parsed
    except Exception:
        pass
    # fallback determinista sin LLM
    nit_match = re.search(r"\b(\d{8,10}(?:-\w)?)\b", metadata_text)
    fuente = "DIAN" if "dian" in metadata_text.lower() else ""
    return {
        "document_metadata": {
            "fuente": fuente,
            "regimen": "",
            "periodo_inicio": "",
            "periodo_fin": "",
            "nit_declarante": nit_match.group(1) if nit_match else "",
        }
    }


def _write_sidecar(path: str, payload: Dict[str, Any]) -> Optional[str]:
    if not payload:
        return None
    data_dir = os.path.dirname(os.path.abspath(path))
    base = os.path.splitext(os.path.basename(path))[0]
    specific = os.path.join(data_dir, f"{base}.meta.json")
    generic = os.path.join(data_dir, ".meta.json")
    try:
        with open(specific, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(generic, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return specific
    except Exception:
        return None


def clean_structured_dataframe(path: str, csv_encoding: Optional[str] = None, chat_id: Optional[int] = None) -> pd.DataFrame:
    """
    Ejecuta el pipeline robusto de ingeniería de datos (determinista + sidecar metadata).
    chat_id es opcional: la persistencia usa la carpeta del archivo (data/{chat_id}/...).
    """
    _ = chat_id  # intencional: el path ya encapsula data/{chat_id}/
    raw, encoding = _read_raw(path, csv_encoding)
    if raw.empty:
        return raw

    # 1) header + metadata sidecar
    header_row = _find_best_header_row(raw)
    metadata_text = _rows_to_metadata_context(raw, header_row)
    metadata_payload = _extract_metadata_with_ollama(metadata_text)
    _write_sidecar(path, metadata_payload)

    # 2) truncar cabecera y expandir delimitadores complejos
    header_vals = raw.iloc[header_row].tolist()
    headers = _dedupe_headers([str(v) if v is not None else "" for v in header_vals])
    data = raw.iloc[header_row + 1 :].copy().reset_index(drop=True)
    data.columns = headers
    data = data.apply(lambda s: s.map(lambda x: _norm_text(x) if isinstance(x, str) else x))
    data = data.replace(r"^\s*$", pd.NA, regex=True).dropna(axis=0, how="all").dropna(axis=1, how="all")
    data, _ = _expand_delimiters(data)

    # 3) tipados locales
    data = _sanitize_local_types(data)

    # 4) armonización difusa
    data = _harmonize_categorical(data)

    # 5) cuarentena y reparación sintética
    data = _coerce_numeric_quarantine(data)
    data = data.ffill(axis=0).fillna("")
    return data


def smart_read_schema(path: str) -> ReadResult:
    """
    API legacy para mostrar esquema. Reusa el pipeline robusto en modo muestra.
    """
    raw, encoding = _read_raw(path, None)
    if raw.empty:
        return ReadResult(
            df=pd.DataFrame(),
            encoding=encoding,
            header_row=0,
            pipe_columns=[],
            was_cleaned=False,
            metadata={},
            metadata_path=None,
        )
    header_row = _find_best_header_row(raw)
    metadata_text = _rows_to_metadata_context(raw, header_row)
    payload = _extract_metadata_with_ollama(metadata_text)
    mpath = _write_sidecar(path, payload)

    cleaned = clean_structured_dataframe(path, csv_encoding=encoding)
    sample = cleaned.head(5).copy() if not cleaned.empty else cleaned
    return ReadResult(
        df=sample,
        encoding=encoding,
        header_row=header_row,
        pipe_columns=[],
        was_cleaned=True,
        metadata=payload,
        metadata_path=mpath,
    )

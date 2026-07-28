"""Validación de columnas referenciadas en código pandas generado por el AnalystAgent."""

from __future__ import annotations

import re
from typing import List, Set


def extract_df_column_refs(codigo: str) -> Set[str]:
    """Extrae nombres de columna referenciados vía df['col'], df[["a","b"]], groupby, etc."""
    if not codigo:
        return set()
    refs: Set[str] = set()
    refs.update(re.findall(r"""df\s*\[\s*['"]([^'"]+)['"]\s*\]""", codigo))
    for block in re.findall(r"""df\s*\[\s*\[(.*?)\]\s*\]""", codigo, re.DOTALL):
        refs.update(re.findall(r"""['"]([^'"]+)['"]""", block))
    for block in re.findall(r"""\.groupby\(\s*\[?(.*?)\]?\s*[,)]""", codigo, re.DOTALL):
        refs.update(re.findall(r"""['"]([^'"]+)['"]""", block))
    for block in re.findall(r"""\.sort_values\(\s*(?:by\s*=\s*)?\[?(.*?)\]?\s*[,)]""", codigo, re.DOTALL):
        refs.update(re.findall(r"""['"]([^'"]+)['"]""", block))
    for block in re.findall(r"""\.loc\s*\[[^\]]*?(?:['"]([^'"]+)['"]|\[(.*?)\])""", codigo, re.DOTALL):
        if block[0]:
            refs.add(block[0])
        if block[1]:
            refs.update(re.findall(r"""['"]([^'"]+)['"]""", block[1]))
    refs.update(re.findall(r"""aggregate_and_build_option\(\s*df\s*,\s*['"]([^'"]+)['"]""", codigo))
    refs.update(re.findall(r"""value_column\s*=\s*['"]([^'"]+)['"]""", codigo))
    return {r for r in refs if r and r.strip()}


def format_columns_hint(schema_columns: List[str]) -> str:
    return ", ".join(f"'{c}'" for c in schema_columns)


def validate_code_columns(codigo: str, schema_columns: List[str]) -> None:
    """Falla temprano si el código usa columnas que no existen en el esquema real."""
    allowed = {str(c) for c in schema_columns}
    allowed_norm = {c.strip(): c for c in allowed}
    refs = extract_df_column_refs(codigo)
    if not refs:
        return
    unknown = []
    for r in refs:
        if r in allowed or r.strip() in allowed_norm:
            continue
        unknown.append(r)
    if unknown:
        disponibles = format_columns_hint(schema_columns)
        raise ValueError(
            f"Columnas inexistentes en el archivo: {unknown}. "
            f"Columnas disponibles: [{disponibles}]. "
            "Usa EXACTAMENTE estos nombres (sin inventar Sector, Categoria, etc.)."
        )

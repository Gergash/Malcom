"""
Geo helpers: map text → Tuluá comuna (1–10) via barrio dictionary.

Does NOT invent geo. Only assigns comuna when text mentions ``Comuna N``
or a barrio listed in ``config/equivalencia_barrio_comuna.csv``.
Ambiguous barrio names require an anchor (``barrio X`` / ``sector X``).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Barrios that appear in non-geo contexts → require "barrio/sector …" prefix
AMBIGUOS = {
    "municipal",
    "el centro",
    "bolivar",
    "avenida cali",
    "victoria",
    "popular",
    "entre rios",
    "tomas uribe uribe",
    "departamental",
    "ruben cruz velez",
    "la villa",
    "el bosque",
    "el dorado",
    "la rivera",
    "fatima",
    "san antonio",
    "la esperanza",
}

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EQ = ROOT / "config" / "equivalencia_barrio_comuna.csv"


def _norm(texto: str) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def load_barrio_index(path: str | None = None) -> Tuple[Tuple[str, int, str], ...]:
    eq_path = Path(path) if path else DEFAULT_EQ
    if not eq_path.exists():
        return tuple()
    filas: List[Tuple[str, int, str]] = []
    with eq_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            b = _norm(str(row.get("barrio") or ""))
            if len(b) < 5:
                continue
            try:
                cid = int(row["comuna_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 1 <= cid <= 10:
                continue
            label = str(row.get("comuna_label") or f"Comuna {cid}")
            filas.append((b, cid, label))
    filas.sort(key=lambda x: -len(x[0]))
    return tuple(filas)


def detectar_comuna(
    texto: str,
    indice: Optional[Tuple[Tuple[str, int, str], ...]] = None,
) -> Optional[Dict[str, Any]]:
    """Return geo match dict or None. Never invents comuna."""
    t = _norm(texto)
    if not t:
        return None
    indice = indice if indice is not None else load_barrio_index()

    m = re.search(r"\bcomuna\s*(\d{1,2})\b", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 10:
            return {
                "comuna_id": n,
                "comuna_label": f"Comuna {n}",
                "match_tipo": "comuna_literal",
                "match_texto": f"comuna {n}",
                "confianza_geo": "alta",
            }

    for barrio, cid, label in indice:
        if barrio in AMBIGUOS:
            pat = rf"\b(?:barrio|sector|urbanizacion|urbanización)\s+{re.escape(barrio)}\b"
            if not re.search(pat, t):
                continue
            conf = "alta"
        else:
            if not re.search(rf"(?<![a-z0-9]){re.escape(barrio)}(?![a-z0-9])", t):
                continue
            conf = "media"
        return {
            "comuna_id": cid,
            "comuna_label": label,
            "match_tipo": "barrio",
            "match_texto": barrio,
            "confianza_geo": conf,
        }
    return None


def sentiment_to_score(label: Optional[str]) -> Optional[float]:
    if not label:
        return None
    key = _norm(label)
    return {
        "positive": 1.0,
        "positivo": 1.0,
        "neutral": 0.0,
        "neutro": 0.0,
        "negative": -1.0,
        "negativo": -1.0,
    }.get(key)

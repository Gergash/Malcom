"""
Paquetes de escucha (alcance) + costos en créditos listening.
El cobro/Bold lo refuerza la API Go; aquí vive la UX de pregunta y el mapeo.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

# Créditos listening ≈ unidades facturables hacia uso Grok (coste operativo).
PACKS: dict[str, dict[str, Any]] = {
    "rapida": {
        "id": "rapida",
        "label": "Rápida",
        "credits": 5,
        "max_sources": 8,
        "days": 3,
        "blurb": "Muestra corta (~3 días, hasta 8 fuentes). Ideal para una vista rápida.",
    },
    "estandar": {
        "id": "estandar",
        "label": "Estándar",
        "credits": 15,
        "max_sources": 20,
        "days": 7,
        "blurb": "Semana reciente, hasta 20 fuentes. Balance costo / cobertura.",
    },
    "profunda": {
        "id": "profunda",
        "label": "Profunda",
        "credits": 40,
        "max_sources": 999,
        "days": 30,
        "blurb": "Mes completo, todas las fuentes activas. Máxima cobertura (más uso de Grok).",
    },
}

# Monto Bold de referencia por paquete (COP) — el webhook Go acredita créditos.
PACK_BOLD_COP: dict[str, int] = {
    "rapida": 15000,
    "estandar": 40000,
    "profunda": 90000,
}


def _pending_path(chat_id: str | int) -> Path:
    root = Path(os.getenv("DATA_DIR") or "data") / str(chat_id)
    root.mkdir(parents=True, exist_ok=True)
    return root / ".listening_pack_pending.json"


def set_pack_pending(chat_id: str | int) -> None:
    path = _pending_path(chat_id)
    path.write_text(
        json.dumps({"pending": True, "ts": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )


def clear_pack_pending(chat_id: str | int) -> None:
    path = _pending_path(chat_id)
    if path.is_file():
        path.unlink(missing_ok=True)


def is_pack_pending(chat_id: str | int) -> bool:
    path = _pending_path(chat_id)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("pending"))
    except (OSError, json.JSONDecodeError):
        return False


def parse_pack_choice(message: str) -> Optional[str]:
    """Detecta rapida|estandar|profunda en el mensaje."""
    lower = (message or "").lower().strip()
    # números 1/2/3
    if re.fullmatch(r"\s*[1]\s*", lower) or "rápida" in lower or "rapida" in lower or "lite" in lower:
        return "rapida"
    if re.fullmatch(r"\s*[2]\s*", lower) or "estándar" in lower or "estandar" in lower or "standard" in lower:
        return "estandar"
    if (
        re.fullmatch(r"\s*[3]\s*", lower)
        or "profunda" in lower
        or "deep" in lower
        or "completa" in lower
        or "exhaustiv" in lower  # exhaustivo / exhaustiva
        or "máxima cobertura" in lower
        or "maxima cobertura" in lower
    ):
        return "profunda"
    # "paquete estándar", etc.
    for pid in PACKS:
        if pid in lower.replace("á", "a"):
            return pid
    if "estandar" in lower.replace("á", "a"):
        return "estandar"
    return None


def pack_selection_prompt() -> str:
    lines = [
        "**Termómetro Cultural — alcance de la recolección**",
        "",
        "¿Qué tan extensa quieres la escucha? El costo se descuenta de tus "
        "**créditos de listening** (se recargan con Bold; ese valor cubre el uso de la API Grok).",
        "",
    ]
    for i, pid in enumerate(("rapida", "estandar", "profunda"), start=1):
        p = PACKS[pid]
        cop = PACK_BOLD_COP.get(pid, 0)
        lines.append(
            f"**{i}. {p['label']}** — {p['credits']} créditos"
            f" (recarga Bold ≈ ${cop:,} COP)".replace(",", ".")
        )
        lines.append(f"   {p['blurb']}")
        lines.append("")
    lines.append("Responde con **1**, **2**, **3**, o el nombre del paquete (*rápida* / *estándar* / *profunda*).")
    return "\n".join(lines)


def insufficient_credits_message(pack_id: str, balance: int) -> str:
    p = PACKS[pack_id]
    cop = PACK_BOLD_COP.get(pack_id, 40000)
    return (
        f"**Créditos de listening insuficientes**\n\n"
        f"El paquete **{p['label']}** requiere **{p['credits']} créditos** "
        f"y tu saldo es **{balance}**.\n\n"
        f"Recarga con Bold (~**${cop:,} COP**) para este paquete. "
        f"El pago se destina a cubrir el uso de la API Grok en la recolección.\n\n"
        f"Usa el botón / enlace de pago Premium-Listening de InsightFlow y vuelve a pedir "
        f"*recolectar termómetro*."
    ).replace(",", ".")

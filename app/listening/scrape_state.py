"""Estado local de la última recolección (archivo en DATA_DIR / data)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

# Tiempo típico del job (mensaje al usuario). Tras esto, si posts=0 → “terminó sin datos”.
ETA_MINUTES = 15
STALE_SECONDS = ETA_MINUTES * 60


def _state_path() -> Path:
    root = Path(os.getenv("DATA_DIR") or "data")
    root.mkdir(parents=True, exist_ok=True)
    return root / ".listening_scrape_state.json"


def save_scrape_queued(scrape_info: dict[str, Any]) -> dict[str, Any]:
    state = {
        "status": "collecting",
        "task_id": scrape_info.get("task_id"),
        "sources_count": scrape_info.get("sources_count"),
        "message": scrape_info.get("message"),
        "queued_at": scrape_info.get("queued_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "started_ts": time.time(),
    }
    path = _state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def load_scrape_state() -> Optional[dict[str, Any]]:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def mark_ready(*, posts: int) -> None:
    state = load_scrape_state() or {}
    state["status"] = "ready" if posts > 0 else "empty"
    state["posts"] = posts
    state["finished_ts"] = time.time()
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_collection_phase(*, posts: int, just_queued: bool = False) -> str:
    """
    collecting | ready | empty | idle
    """
    if just_queued:
        return "collecting"
    if posts > 0:
        state = load_scrape_state()
        if state and state.get("status") == "collecting":
            mark_ready(posts=posts)
        return "ready"

    state = load_scrape_state()
    if not state:
        return "idle"
    if state.get("status") == "collecting":
        started = float(state.get("started_ts") or 0)
        if started and (time.time() - started) < STALE_SECONDS:
            return "collecting"
        mark_ready(posts=0)
        return "empty"
    if state.get("status") == "ready":
        return "ready" if posts > 0 else "empty"
    return state.get("status") or "idle"

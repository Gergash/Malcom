"""Estado local de la última recolección (archivo en DATA_DIR / data)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

# Tiempo típico del job (mensaje al usuario). Tras esto, si no hay posts nuevos → “terminó”.
ETA_MINUTES = 15
STALE_SECONDS = ETA_MINUTES * 60


def _state_path() -> Path:
    root = Path(os.getenv("DATA_DIR") or "data")
    root.mkdir(parents=True, exist_ok=True)
    return root / ".listening_scrape_state.json"


def save_scrape_queued(
    scrape_info: dict[str, Any],
    *,
    posts_baseline: int = 0,
) -> dict[str, Any]:
    state = {
        "status": "collecting",
        "task_id": scrape_info.get("task_id"),
        "sources_count": scrape_info.get("sources_count"),
        "message": scrape_info.get("message"),
        "queued_at": scrape_info.get("queued_at")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "started_ts": time.time(),
        "posts_baseline": int(posts_baseline or 0),
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


def mark_ready(*, posts: int, new_posts: Optional[int] = None) -> None:
    state = load_scrape_state() or {}
    state["status"] = "ready" if posts > 0 else "empty"
    state["posts"] = posts
    if new_posts is not None:
        state["new_posts"] = int(new_posts)
    state["finished_ts"] = time.time()
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def time_based_percent(state: Optional[dict[str, Any]]) -> int:
    """Estimación suave 2→90% por tiempo, hasta que haya progreso Celery real."""
    if not state:
        return 5
    started = float(state.get("started_ts") or 0)
    if not started:
        return 5
    elapsed = max(0.0, time.time() - started)
    return max(2, min(90, int(round(100.0 * elapsed / STALE_SECONDS))))


def resolve_collection_phase(
    *,
    posts: int,
    just_queued: bool = False,
    celery_ready: bool = False,
    has_celery_status: bool = False,
    new_posts: Optional[int] = None,
) -> str:
    """
    collecting | ready | ready_no_new | empty | idle

    Con estado Celery: no marcar ready hasta celery_ready (aunque ya haya posts).
    Si Celery termina con new_posts=0 → ready_no_new (no fingir datos frescos).
    """
    if just_queued:
        return "collecting"

    state = load_scrape_state()
    if state and state.get("status") == "collecting":
        started = float(state.get("started_ts") or 0)
        baseline = int(state.get("posts_baseline") or 0)
        within_window = bool(started and (time.time() - started) < STALE_SECONDS)

        if has_celery_status:
            if celery_ready:
                mark_ready(posts=posts, new_posts=new_posts)
                if new_posts is not None and int(new_posts) <= 0:
                    return "ready_no_new" if posts > 0 else "empty"
                if posts <= baseline:
                    return "ready_no_new" if posts > 0 else "empty"
                return "ready"
            if within_window:
                return "collecting"
            mark_ready(posts=posts, new_posts=new_posts if new_posts is not None else 0)
            return "ready_no_new" if posts > 0 else "empty"

        # Fallback sin Celery: posts nuevos o ventana
        if posts > baseline:
            mark_ready(posts=posts)
            return "ready"
        if within_window:
            return "collecting"
        mark_ready(posts=posts, new_posts=0)
        return "ready_no_new" if posts > 0 else "empty"

    # Ya marcado ready: si la última corrida no trajo posts, ser honestos
    if state and state.get("status") == "ready":
        last_new = state.get("new_posts")
        if posts > 0 and last_new is not None and int(last_new) <= 0:
            return "ready_no_new"
        return "ready" if posts > 0 else "empty"

    if posts > 0:
        return "ready"
    if not state:
        return "idle"
    if state.get("status") == "empty":
        return "empty"
    return state.get("status") or "idle"

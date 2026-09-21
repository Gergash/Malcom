"""Idempotent seed of monitoring sources from YAML config.

Default: config/sources_tulua.yaml
Override: env LISTENING_SOURCES_FILE (ruta relativa a services/listening_engine/
          o absoluta), p. ej. config/sources_cgfm.yaml
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import structlog
import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

_ENGINE_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REL = "config/sources_tulua.yaml"


def _config_path() -> Path:
    raw = (os.getenv("LISTENING_SOURCES_FILE") or "").strip()
    if not raw:
        return _ENGINE_ROOT / _DEFAULT_REL
    p = Path(raw)
    if not p.is_absolute():
        p = _ENGINE_ROOT / p
    return p


def _load_sources_config() -> List[Dict[str, Any]]:
    path = _config_path()
    if not path.is_file():
        logger.warning("sources_config_missing", path=str(path))
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        logger.warning("sources_config_invalid", path=str(path))
        return []
    logger.info("sources_config_loaded", path=str(path), count=len(sources))
    return sources


def seed_sources(session: Session) -> int:
    """
    Insert sources from YAML when no row exists with the same name.
    Returns count of newly inserted rows.
    """
    inserted = 0
    for row in _load_sources_config():
        name = (row.get("name") or "").strip()
        platform = (row.get("platform") or "").strip().lower()
        url = (row.get("url") or "").strip()
        is_active = bool(row.get("is_active", True))
        if not name or not platform or not url:
            logger.warning("source_seed_skipped_invalid", row=row)
            continue

        exists = session.execute(
            text("SELECT 1 FROM sources WHERE name = :name LIMIT 1"),
            {"name": name},
        ).first()
        if exists:
            continue

        session.execute(
            text(
                "INSERT INTO sources (name, platform, url, is_active) "
                "VALUES (:name, :platform, :url, :is_active)"
            ),
            {
                "name": name,
                "platform": platform,
                "url": url,
                "is_active": is_active,
            },
        )
        inserted += 1
        logger.info("source_seeded", name=name, platform=platform, url=url[:80])

    return inserted

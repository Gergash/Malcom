"""Idempotent seed of monitoring sources from YAML config.

Default: config/sources_tulua.yaml
Override: env LISTENING_SOURCES_FILE (ruta relativa a services/listening_engine/
          o absoluta), p. ej. config/sources_cgfm.yaml

Con LISTENING_SOURCES_FILE definido, el seed:
  - inserta fuentes nuevas
  - actualiza url/platform/is_active de las existentes (mismo name)
  - desactiva fuentes que NO estén en el YAML (perfil exclusivo CGFM)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Set

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


def _exclusive_profile() -> bool:
    """Si hay archivo override (p. ej. CGFM), el YAML es la fuente de verdad."""
    return bool((os.getenv("LISTENING_SOURCES_FILE") or "").strip())


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
    Upsert sources from YAML. Returns count of newly inserted rows.
    """
    inserted = 0
    yaml_names: Set[str] = set()
    exclusive = _exclusive_profile()

    for row in _load_sources_config():
        name = (row.get("name") or "").strip()
        platform = (row.get("platform") or "").strip().lower()
        url = (row.get("url") or "").strip()
        is_active = bool(row.get("is_active", True))
        if not name or not platform or not url:
            logger.warning("source_seed_skipped_invalid", row=row)
            continue

        yaml_names.add(name)

        exists = session.execute(
            text("SELECT id FROM sources WHERE name = :name LIMIT 1"),
            {"name": name},
        ).first()
        if exists:
            session.execute(
                text(
                    "UPDATE sources SET platform = :platform, url = :url, "
                    "is_active = :is_active WHERE name = :name"
                ),
                {
                    "name": name,
                    "platform": platform,
                    "url": url,
                    "is_active": is_active,
                },
            )
            logger.info(
                "source_seed_updated",
                name=name,
                platform=platform,
                is_active=is_active,
            )
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

    if exclusive and yaml_names:
        # Desactivar residuales (p. ej. Tuluá) que no están en el perfil CGFM
        rows = session.execute(text("SELECT id, name FROM sources")).fetchall()
        deactivated = 0
        for row in rows:
            if row.name not in yaml_names:
                session.execute(
                    text("UPDATE sources SET is_active = false WHERE id = :id"),
                    {"id": row.id},
                )
                deactivated += 1
                logger.info("source_deactivated_not_in_profile", name=row.name)
        if deactivated:
            logger.info("sources_exclusive_cleanup", deactivated=deactivated)

    return inserted

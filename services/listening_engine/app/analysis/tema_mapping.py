"""Maps internal topic taxonomy slugs to the external pauta-meta `tema` categories.

The canonical mapping lives in ``config/topic_tema_mapping.yaml``.
``TEMA_MAPPING_VERSION`` is bumped whenever that file's ``version`` changes.
"""
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "topic_tema_mapping.yaml"

# Fallback if YAML is missing (tests / minimal deploys)
_DEFAULT_MAPPING: Dict[str, Optional[str]] = {
    "security": "SEGURIDAD",
    "taxes": "ECONOMIA",
    "public_services": "INSTITUCIONAL",
    "infrastructure": "INFRAESTRUCTURA",
    "corruption": None,
    "public_administration": "INSTITUCIONAL",
    "other": None,
}

TEMA_MAPPING_VERSION = "1.0.0"
TOPIC_TO_TEMA: Dict[str, Optional[str]] = dict(_DEFAULT_MAPPING)

# Stable iteration order for priority-score responses
TAXONOMY_SLUGS = list(_DEFAULT_MAPPING.keys())


@lru_cache
def _load_mapping_file() -> tuple[str, Dict[str, Optional[str]]]:
    if not _CONFIG_PATH.exists():
        return TEMA_MAPPING_VERSION, dict(_DEFAULT_MAPPING)

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    version = str(data.get("version", TEMA_MAPPING_VERSION))
    raw = data.get("mapping") or {}
    mapping: Dict[str, Optional[str]] = {}
    for slug, tema in raw.items():
        mapping[str(slug)] = None if tema is None else str(tema)
    return version, mapping


def reload_tema_mapping() -> None:
    """Clear cached YAML load (useful in tests)."""
    _load_mapping_file.cache_clear()
    global TEMA_MAPPING_VERSION, TOPIC_TO_TEMA
    version, mapping = _load_mapping_file()
    TEMA_MAPPING_VERSION = version
    TOPIC_TO_TEMA = mapping
    global TAXONOMY_SLUGS
    TAXONOMY_SLUGS = list(mapping.keys())


# Initialise module-level constants from YAML on import
reload_tema_mapping()


def pauta_tema_for(slug: str) -> Optional[str]:
    """Return the pauta ``tema`` for a known topic slug, or ``None`` when the
    topic has no ``tema`` mapping. Raises ``KeyError`` for an unknown slug —
    an unrecognized slug is a taxonomy bug, not a "no mapping" case.
    """
    return TOPIC_TO_TEMA[slug]

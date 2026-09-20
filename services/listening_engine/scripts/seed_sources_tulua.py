#!/usr/bin/env python3
"""Seed Tuluá monitoring sources from config/sources_tulua.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scheduler.repository import _session  # noqa: E402
from app.scheduler.source_seeds import seed_sources  # noqa: E402


def main() -> int:
    session = _session()
    try:
        inserted = seed_sources(session)
        session.commit()
        print(f"Sources seeded: {inserted} new row(s)")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

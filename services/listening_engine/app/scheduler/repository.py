"""
Synchronous DB repository for the scheduler layer.

Celery tasks run in standard (non-async) worker processes.
All DB operations here use the sync SQLAlchemy engine (DATABASE_URL_SYNC).

Public API:
    get_active_sources()                         → List[Source]
    upsert_post(source_id, item)                 → (post_id, is_new: bool)
    get_unprocessed_posts(limit, post_ids)        → List[dict]
    get_or_create_sentiment_score(label)          → int (id)
    get_topic_id_by_slug(slug)                   → Optional[int]
    save_analysis_result(post_id, record, ...)   → int (id)
    update_post_cache(post_id, sentiment, urgency, confidence, language)
    get_stale_posts(limit)                       → List[dict]
    seed_lookup_tables()                         → None
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Engine / session factory (one engine per worker process via lru_cache)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _engine():
    s = get_settings()
    return create_engine(
        s.database_url_sync,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def _session() -> Session:
    return sessionmaker(bind=_engine(), autocommit=False, autoflush=False)()


# ---------------------------------------------------------------------------
# Seed lookup tables
# ---------------------------------------------------------------------------

_SENTIMENT_SEEDS = [
    {"label": "positive", "score_value": Decimal("1.0000"),  "description": "Positive sentiment"},
    {"label": "neutral",  "score_value": Decimal("0.0000"),  "description": "Neutral sentiment"},
    {"label": "negative", "score_value": Decimal("-1.0000"), "description": "Negative sentiment"},
]

_TOPIC_SEEDS = [
    {"slug": "security",              "name": "Seguridad"},
    {"slug": "taxes",                 "name": "Impuestos y Cobros"},
    {"slug": "public_services",       "name": "Servicios Públicos"},
    {"slug": "infrastructure",        "name": "Infraestructura"},
    {"slug": "corruption",            "name": "Corrupción"},
    {"slug": "public_administration", "name": "Administración Pública"},
    {"slug": "other",                 "name": "Otros"},
]


def seed_lookup_tables() -> None:
    """
    Idempotent seed: inserts sentiment_scores and topics rows if they don't exist.
    Called once per worker startup.
    """
    session = _session()
    try:
        for row in _SENTIMENT_SEEDS:
            session.execute(
                text(
                    "INSERT INTO sentiment_scores (label, score_value, description) "
                    "VALUES (:label, :score_value, :description) "
                    "ON CONFLICT (label) DO NOTHING"
                ),
                row,
            )
        for row in _TOPIC_SEEDS:
            session.execute(
                text(
                    "INSERT INTO topics (slug, name) VALUES (:slug, :name) "
                    "ON CONFLICT (slug) DO NOTHING"
                ),
                row,
            )
        from app.scheduler.source_seeds import seed_sources

        sources_inserted = seed_sources(session)
        session.commit()
        logger.info("seed_lookup_tables_ok", sources_inserted=sources_inserted)
    except Exception:
        session.rollback()
        logger.exception("seed_lookup_tables_failed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def get_active_sources() -> List[Dict[str, Any]]:
    """Return all active sources as plain dicts."""
    session = _session()
    try:
        rows = session.execute(
            text("SELECT id, name, platform, url FROM sources WHERE is_active = true ORDER BY id")
        ).fetchall()
        return [{"id": r.id, "name": r.name, "platform": r.platform, "url": r.url} for r in rows]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def _extract_comment_texts(metadata: Any) -> List[str]:
    """Pull comment strings from scraper metadata (comments_sample / comments)."""
    if not isinstance(metadata, dict):
        return []
    texts: List[str] = []

    def _add(raw: Any) -> None:
        if isinstance(raw, str):
            t = raw.strip()
            if t:
                texts.append(t[:2000])
        elif isinstance(raw, dict):
            t = str(raw.get("text") or "").strip()
            if t:
                texts.append(t[:2000])

    sample = metadata.get("comments_sample")
    if isinstance(sample, list):
        for item in sample:
            _add(item)

    comments = metadata.get("comments")
    if isinstance(comments, list):
        for item in comments:
            _add(item)

    # de-dupe preserving order
    seen = set()
    out: List[str] = []
    for t in texts:
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def save_comments_for_post(
    post_id: int,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    texts: Optional[List[str]] = None,
) -> int:
    """
    Persist comment texts for a post (Ley 1581 sanitization per comment).
    Dedupes by (post_id, exact text). Returns number of NEW comments inserted.
    """
    from app.processing.privacy import sanitize

    raw_texts = list(texts or [])
    if metadata:
        raw_texts.extend(_extract_comment_texts(metadata))

    cleaned: List[str] = []
    for t in raw_texts:
        if not t or not str(t).strip():
            continue
        sanitized, _report = sanitize(str(t).strip()[:2000])
        if sanitized.strip():
            cleaned.append(sanitized.strip())

    if not cleaned:
        return 0

    session = _session()
    inserted = 0
    try:
        for text_val in cleaned:
            existing = session.execute(
                text(
                    "SELECT id FROM comments "
                    "WHERE post_id = :post_id AND text = :text LIMIT 1"
                ),
                {"post_id": post_id, "text": text_val},
            ).fetchone()
            if existing:
                continue
            session.execute(
                text(
                    "INSERT INTO comments (post_id, text, metadata) "
                    "VALUES (:post_id, :text, CAST(:metadata AS jsonb))"
                ),
                {
                    "post_id": post_id,
                    "text": text_val,
                    "metadata": __import__("json").dumps({"source": "scraper_metadata"}),
                },
            )
            inserted += 1
        session.commit()
        if inserted:
            logger.info("comments_saved", post_id=post_id, inserted=inserted)
        return inserted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def backfill_comments_from_post_metadata(limit: int = 500) -> Dict[str, int]:
    """
    Scan posts.metadata for comments_sample / comments and persist into comments.
    Safe to re-run (deduped).
    """
    import json as _json

    session = _session()
    scanned = 0
    inserted_total = 0
    try:
        rows = session.execute(
            text(
                "SELECT id, metadata FROM posts "
                "WHERE metadata IS NOT NULL "
                "  AND ("
                "    (jsonb_typeof(metadata->'comments_sample') = 'array' "
                "      AND jsonb_array_length(metadata->'comments_sample') > 0) "
                "    OR (jsonb_typeof(metadata->'comments') = 'array' "
                "      AND jsonb_array_length(metadata->'comments') > 0)"
                "  ) "
                "ORDER BY id DESC LIMIT :limit"
            ),
            {"limit": limit},
        ).fetchall()
        session.close()
    except Exception:
        session.close()
        raise

    for row in rows:
        scanned += 1
        meta = row.metadata
        if isinstance(meta, str):
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}
        inserted_total += save_comments_for_post(row.id, meta if isinstance(meta, dict) else {})

    logger.info("comments_backfill_done", scanned=scanned, inserted=inserted_total)
    return {"scanned": scanned, "inserted": inserted_total}


def get_unprocessed_comments(
    limit: int = 100,
    post_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Comments with no AnalysisResult linked via comment_id."""
    session = _session()
    try:
        sql = (
            "SELECT c.id, c.post_id, c.text, p.platform, p.url "
            "FROM comments c "
            "JOIN posts p ON p.id = c.post_id "
            "LEFT JOIN analysis_results ar ON ar.comment_id = c.id "
            "WHERE ar.id IS NULL "
        )
        params: Dict[str, Any] = {"limit": limit}
        if post_ids:
            sql += "AND c.post_id = ANY(:post_ids) "
            params["post_ids"] = post_ids
        sql += "ORDER BY c.scraped_at DESC LIMIT :limit"
        rows = session.execute(text(sql), params).fetchall()
        return [
            {
                "id": r.id,
                "post_id": r.post_id,
                "text": r.text,
                "platform": r.platform,
                "url": r.url,
            }
            for r in rows
        ]
    finally:
        session.close()

# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

def upsert_post(source_id: int, item: Dict[str, Any]) -> Tuple[int, bool]:
    """
    Insert a post if its URL doesn't exist yet.
    Applies Ley 1581 privacy sanitization before storage.
    Returns (post_id, is_new).
    """
    # Privacy layer: remove PII before any data reaches the database
    from app.processing.privacy import sanitize_record as _sanitize
    item, privacy_report = _sanitize(item)
    if privacy_report.has_pii:
        logger.info(
            "repository_pii_removed",
            mentions=privacy_report.mentions_removed,
            emails=privacy_report.emails_removed,
            phones=privacy_report.phones_removed,
            cedulas=privacy_report.cedulas_removed,
            metadata_keys=privacy_report.metadata_keys_cleared,
        )

    url = (item.get("url") or "").strip()
    if not url:
        raise ValueError("scraped item has no URL")

    session = _session()
    try:
        existing = session.execute(
            text("SELECT id FROM posts WHERE url = :url LIMIT 1"), {"url": url}
        ).fetchone()

        if existing:
            return existing.id, False

        result = session.execute(
            text(
                "INSERT INTO posts (source_id, platform, text, posted_at, url, metadata, language) "
                "VALUES (:source_id, :platform, :text, :posted_at, :url, CAST(:metadata AS jsonb), :language) "
                "RETURNING id"
            ),
            {
                "source_id": source_id,
                "platform":  item.get("platform", ""),
                "text":      item.get("text", ""),
                "posted_at": item.get("date"),
                "url":       url,
                "metadata":  __import__("json").dumps(item.get("metadata") or {}),
                "language":  item.get("language"),
            },
        )
        post_id: int = result.fetchone().id
        session.commit()
        return post_id, True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_unprocessed_posts(
    limit: int = 100,
    post_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Return posts that have no AnalysisResult yet.
    If post_ids is provided, restrict to those IDs.
    """
    session = _session()
    try:
        base = (
            "SELECT p.id, p.text, p.platform, p.url, p.source_id, s.name AS source_name "
            "FROM posts p "
            "LEFT JOIN sources s ON s.id = p.source_id "
            "LEFT JOIN analysis_results ar ON ar.post_id = p.id "
            "WHERE ar.id IS NULL "
        )
        params: Dict[str, Any] = {"limit": limit}

        if post_ids:
            base += "AND p.id = ANY(:post_ids) "
            params["post_ids"] = post_ids

        base += "ORDER BY p.scraped_at DESC LIMIT :limit"
        rows = session.execute(text(base), params).fetchall()
        return [
            {
                "id":          r.id,
                "text":        r.text,
                "platform":    r.platform,
                "url":         r.url,
                "source_id":   r.source_id,
                "source_name": r.source_name or "",
            }
            for r in rows
        ]
    finally:
        session.close()


def get_stale_posts(limit: int = 500) -> List[Dict[str, Any]]:
    """
    Posts that have an AnalysisResult but whose cached_* fields are NULL.
    Used by update_analytics to reconcile the cache.
    """
    session = _session()
    try:
        rows = session.execute(
            text(
                "SELECT p.id, ar.id AS ar_id, ss.label AS sentiment, "
                "       ar.urgency, ar.confidence "
                "FROM posts p "
                "JOIN analysis_results ar ON ar.post_id = p.id "
                "LEFT JOIN sentiment_scores ss ON ss.id = ar.sentiment_score_id "
                "WHERE p.cached_sentiment_label IS NULL "
                "   OR p.cached_urgency IS NULL "
                "ORDER BY p.scraped_at DESC "
                "LIMIT :limit"
            ),
            {"limit": limit},
        ).fetchall()
        return [
            {
                "post_id":   r.id,
                "sentiment": r.sentiment,
                "urgency":   r.urgency,
                "confidence": float(r.confidence) if r.confidence is not None else None,
            }
            for r in rows
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

def get_or_create_sentiment_score(label: str) -> int:
    """Return sentiment_score.id for label, creating it if missing."""
    _SCORE_MAP = {"positive": Decimal("1.0"), "neutral": Decimal("0.0"), "negative": Decimal("-1.0")}
    session = _session()
    try:
        row = session.execute(
            text("SELECT id FROM sentiment_scores WHERE label = :label"), {"label": label}
        ).fetchone()
        if row:
            return row.id
        result = session.execute(
            text(
                "INSERT INTO sentiment_scores (label, score_value) "
                "VALUES (:label, :score) RETURNING id"
            ),
            {"label": label, "score": _SCORE_MAP.get(label, Decimal("0.0"))},
        )
        sid = result.fetchone().id
        session.commit()
        return sid
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_topic_id_by_slug(slug: str) -> Optional[int]:
    """Return topics.id for slug, or None if not seeded."""
    session = _session()
    try:
        row = session.execute(
            text("SELECT id FROM topics WHERE slug = :slug"), {"slug": slug}
        ).fetchone()
        return row.id if row else None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------

def save_analysis_result(
    post_id: Optional[int],
    sentiment_label: str,
    urgency: str,
    confidence: float,
    topic_slug: str,
    model_version: str = "pipeline-v1",
    *,
    comment_id: Optional[int] = None,
) -> int:
    """
    Create an AnalysisResult for a post and/or comment.
    Exactly one of post_id / comment_id should be the primary subject;
    for comments we still store parent post_id when available for joins.
    """
    if post_id is None and comment_id is None:
        raise ValueError("save_analysis_result requires post_id and/or comment_id")

    sentiment_score_id = get_or_create_sentiment_score(sentiment_label)
    topic_id = get_topic_id_by_slug(topic_slug)

    session = _session()
    try:
        result = session.execute(
            text(
                "INSERT INTO analysis_results "
                "  (post_id, comment_id, sentiment_score_id, urgency, confidence, model_version) "
                "VALUES (:post_id, :comment_id, :ss_id, :urgency, :confidence, :model_version) "
                "RETURNING id"
            ),
            {
                "post_id":       post_id,
                "comment_id":    comment_id,
                "ss_id":         sentiment_score_id,
                "urgency":       urgency,
                "confidence":    Decimal(str(round(confidence, 4))),
                "model_version": model_version,
            },
        )
        ar_id: int = result.fetchone().id

        if topic_id:
            session.execute(
                text(
                    "INSERT INTO analysis_result_topics (analysis_result_id, topic_id) "
                    "VALUES (:ar_id, :topic_id) ON CONFLICT DO NOTHING"
                ),
                {"ar_id": ar_id, "topic_id": topic_id},
            )

        session.commit()
        return ar_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_post_cache(
    post_id: int,
    sentiment_label: str,
    urgency: str,
    confidence: float,
    language: Optional[str] = None,
) -> None:
    """Update Post.cached_* fields and language from the latest analysis result."""
    session = _session()
    try:
        params: Dict[str, Any] = {
            "sentiment": sentiment_label,
            "urgency":   urgency,
            "confidence": Decimal(str(round(confidence, 4))),
            "post_id":   post_id,
        }
        if language:
            session.execute(
                text(
                    "UPDATE posts SET "
                    "  cached_sentiment_label = :sentiment, "
                    "  cached_urgency = :urgency, "
                    "  cached_confidence = :confidence, "
                    "  language = :language "
                    "WHERE id = :post_id"
                ),
                {**params, "language": language},
            )
        else:
            session.execute(
                text(
                    "UPDATE posts SET "
                    "  cached_sentiment_label = :sentiment, "
                    "  cached_urgency = :urgency, "
                    "  cached_confidence = :confidence "
                    "WHERE id = :post_id"
                ),
                params,
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

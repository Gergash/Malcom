"""
Priority-topic aggregation for pauta-meta integration.

Exposes raw citizen-concern signals per taxonomy topic (volume, sentiment,
urgency) plus an optional reference index. Budget weighting stays in
pauta-meta — this module does not auto-adjust Meta Ads spend.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import _pct, _score, get_trending_topics
from app.analysis.tema_mapping import TAXONOMY_SLUGS, TEMA_MAPPING_VERSION, pauta_tema_for
from app.storage.models.topics import Topic

# Topics where paid amplification requires explicit human review (spec R10).
SENSITIVE_TOPIC_SLUGS = frozenset({"corruption", "security"})

REFERENCE_INDEX_FORMULA = (
    "reference_priority_index = round(min(100, "
    "(negative_pct/100 * 60 + urgency_high_pct/100 * 40) * (1 + log10(count+1)/2)), 1)"
)


def compute_reference_priority_index(
    *,
    count: int,
    negative: int,
    urgency_high: int,
) -> float:
    """Non-binding concern index (0–100). Higher = more citizen pressure on topic."""
    if count <= 0:
        return 0.0
    negative_pct = negative / count * 100
    urgency_high_pct = urgency_high / count * 100
    base = negative_pct / 100 * 60 + urgency_high_pct / 100 * 40
    volume_factor = 1 + math.log10(count + 1) / 2
    return round(min(100.0, base * volume_factor), 1)


async def get_priority_topics(
    db: AsyncSession,
    filters,
) -> Dict[str, Any]:
    """All taxonomy topics with raw signals for pauta-meta budget advisory.

    Unlike ``get_trending_topics``, returns every slug in the taxonomy (including
    zero-count topics) so consumers can join against the full TEMA vocabulary.
    """
    trending = await get_trending_topics(db, filters, limit=len(TAXONOMY_SLUGS) + 5)
    stats_by_slug = {t["slug"]: t for t in trending["topics"]}
    total_classified = trending["total_classified"]

    # Topic display names from DB (fallback to slug title-case)
    rows = (await db.execute(select(Topic.slug, Topic.name))).all()
    names = {r.slug: r.name for r in rows}

    topics: List[Dict[str, Any]] = []
    for slug in TAXONOMY_SLUGS:
        stats = stats_by_slug.get(slug, {})
        count = int(stats.get("count", 0))
        positive = int(stats.get("positive", 0))
        neutral = int(stats.get("neutral", 0))
        negative = int(stats.get("negative", 0))
        urgency_high = int(stats.get("urgency_high", 0))
        share_pct = stats.get("share_pct", _pct(count, total_classified))

        pauta_tema = pauta_tema_for(slug)
        requires_human_review = slug in SENSITIVE_TOPIC_SLUGS and (
            urgency_high > 0 or negative > 0
        )

        topics.append({
            "slug": slug,
            "name": names.get(slug, slug.replace("_", " ").title()),
            "count": count,
            "share_pct": share_pct,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "negative_pct": _pct(negative, count),
            "urgency_high": urgency_high,
            "urgency_high_pct": _pct(urgency_high, count),
            "sentiment_score": _score(positive, negative, count),
            "pauta_tema": pauta_tema,
            "requires_human_review": requires_human_review,
            "reference_priority_index": compute_reference_priority_index(
                count=count,
                negative=negative,
                urgency_high=urgency_high,
            ),
        })

    topics.sort(key=lambda t: (-t["reference_priority_index"], -t["count"], t["slug"]))

    return {
        "topics": topics,
        "total_classified": total_classified,
        "tema_mapping_version": TEMA_MAPPING_VERSION,
        "reference_index_formula": REFERENCE_INDEX_FORMULA,
        "sensitive_topic_slugs": sorted(SENSITIVE_TOPIC_SLUGS),
    }

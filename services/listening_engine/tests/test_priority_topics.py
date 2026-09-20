"""Tests for priority-topic aggregation (pauta-meta integration)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.priority import compute_reference_priority_index, get_priority_topics


class _Filters:
    def __init__(self, from_date=None, to_date=None):
        self.from_date = from_date
        self.to_date = to_date
        self.platform = None
        self.topic = None


def test_compute_reference_priority_index_zero_count():
    assert compute_reference_priority_index(count=0, negative=5, urgency_high=2) == 0.0


def test_compute_reference_priority_index_increases_with_negative_and_urgency():
    low = compute_reference_priority_index(count=10, negative=2, urgency_high=1)
    high = compute_reference_priority_index(count=10, negative=8, urgency_high=5)
    assert high > low


@pytest.mark.asyncio
async def test_get_priority_topics_returns_all_taxonomy_slugs(db_session, seed_topics, seed_priority_data):
    now = datetime.now(tz=timezone.utc)
    await seed_priority_data(
        topic_slug="security",
        sentiment_label="negative",
        urgency="high",
        posted_at=now - timedelta(days=2),
    )
    await seed_priority_data(
        topic_slug="infrastructure",
        sentiment_label="neutral",
        urgency="low",
        posted_at=now - timedelta(days=1),
    )

    filters = _Filters(from_date=now - timedelta(days=30), to_date=now)
    data = await get_priority_topics(db_session, filters)

    slugs = [t["slug"] for t in data["topics"]]
    assert len(slugs) == 7
    assert "security" in slugs
    assert "other" in slugs

    security = next(t for t in data["topics"] if t["slug"] == "security")
    assert security["count"] == 1
    assert security["negative"] == 1
    assert security["urgency_high"] == 1
    assert security["pauta_tema"] == "SEGURIDAD"
    assert security["requires_human_review"] is True
    assert security["reference_priority_index"] > 0

    other = next(t for t in data["topics"] if t["slug"] == "other")
    assert other["count"] == 0
    assert other["reference_priority_index"] == 0.0


@pytest.mark.asyncio
async def test_get_priority_topics_corruption_requires_review_when_negative(
    db_session, seed_topics, seed_priority_data
):
    now = datetime.now(tz=timezone.utc)
    await seed_priority_data(
        topic_slug="corruption",
        sentiment_label="negative",
        urgency="medium",
        posted_at=now,
    )

    filters = _Filters(from_date=now - timedelta(days=7), to_date=now)
    data = await get_priority_topics(db_session, filters)
    corruption = next(t for t in data["topics"] if t["slug"] == "corruption")

    assert corruption["pauta_tema"] is None
    assert corruption["requires_human_review"] is True

"""Smoke-checks for the `seed_topics` / `seed_priority_data` fixtures themselves.

These fixtures are consumed by PR2's aggregation tests; this file only proves
they build a valid, queryable graph of rows before PR2 depends on them.
"""
import pytest
from sqlalchemy import func, select

from app.storage.models.analysis_results import AnalysisResult
from app.storage.models.topics import Topic


@pytest.mark.asyncio
async def test_seed_topics_inserts_all_seven_slugs(db_session, seed_topics):
    result = await db_session.execute(select(func.count()).select_from(Topic))
    assert result.scalar_one() == 7


@pytest.mark.asyncio
async def test_seed_priority_data_links_post_to_topic(db_session, seed_priority_data):
    analysis_result = await seed_priority_data(
        topic_slug="security", sentiment_label="negative", urgency="high"
    )

    result = await db_session.execute(
        select(AnalysisResult).where(AnalysisResult.id == analysis_result.id)
    )
    fetched = result.scalar_one()
    assert fetched.urgency == "high"
    assert [t.slug for t in fetched.topics] == ["security"]

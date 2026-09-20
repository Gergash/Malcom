"""Smoke tests for the async Postgres test-database fixtures.

Confirms `db_session` yields a working AsyncSession against the real
Postgres+JSONB dialect, and that each test's writes are rolled back so
tests never leak state into one another.
"""
import pytest
from sqlalchemy import select

from app.storage.models.topics import Topic


@pytest.mark.asyncio
async def test_db_session_insert_visible_within_same_test(db_session):
    db_session.add(Topic(name="Rollback Probe", slug="rollback-probe"))
    await db_session.flush()

    result = await db_session.execute(select(Topic).where(Topic.slug == "rollback-probe"))
    assert result.scalar_one().name == "Rollback Probe"


@pytest.mark.asyncio
async def test_db_session_rolls_back_between_tests(db_session):
    result = await db_session.execute(select(Topic).where(Topic.slug == "rollback-probe"))
    assert result.scalar_one_or_none() is None

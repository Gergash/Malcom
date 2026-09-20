"""Pytest configuration and fixtures."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.db_fixtures import get_test_engine, reset_schema

from app.storage.models.analysis_results import AnalysisResult
from app.storage.models.posts import Post
from app.storage.models.sentiment_scores import SentimentScore
from app.storage.models.topics import Topic

TAXONOMY_SLUGS = [
    "security",
    "taxes",
    "public_services",
    "infrastructure",
    "corruption",
    "public_administration",
    "other",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def _test_engine():
    engine = get_test_engine()
    await reset_schema(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test AsyncSession wrapped in an outer transaction that always rolls back.

    Uses a SAVEPOINT so code under test can freely commit/rollback without
    ever persisting data past the test boundary.
    """
    async with _test_engine.connect() as conn:
        outer_trans = await conn.begin()
        session_factory = async_sessionmaker(bind=conn, expire_on_commit=False, class_=AsyncSession)
        session = session_factory()

        await conn.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await outer_trans.rollback()


@pytest_asyncio.fixture
async def seed_topics(db_session: AsyncSession) -> List[Topic]:
    """Insert the 7 fixed taxonomy topics with no posts attached."""
    topics = [Topic(name=slug.replace("_", " ").title(), slug=slug) for slug in TAXONOMY_SLUGS]
    db_session.add_all(topics)
    await db_session.flush()
    return topics


@pytest_asyncio.fixture
def seed_priority_data(db_session: AsyncSession, seed_topics: List[Topic]):
    """Factory fixture: create a Post + AnalysisResult + SentimentScore chain
    linked to a topic by slug, parametrizable per call.
    """
    topics_by_slug: Dict[str, Topic] = {t.slug: t for t in seed_topics}
    sentiment_cache: Dict[str, SentimentScore] = {}

    async def _make(
        *,
        topic_slug: str,
        sentiment_label: str = "neutral",
        urgency: Optional[str] = "low",
        posted_at: Optional[datetime] = None,
    ) -> AnalysisResult:
        topic = topics_by_slug[topic_slug]

        sentiment = sentiment_cache.get(sentiment_label)
        if sentiment is None:
            score_by_label = {"positive": Decimal("1.0"), "neutral": Decimal("0.0"), "negative": Decimal("-1.0")}
            sentiment = SentimentScore(
                label=sentiment_label,
                score_value=score_by_label.get(sentiment_label, Decimal("0.0")),
            )
            db_session.add(sentiment)
            await db_session.flush()
            sentiment_cache[sentiment_label] = sentiment

        post = Post(
            platform="news",
            text=f"seed post for {topic_slug}",
            posted_at=posted_at or datetime.now(timezone.utc),
            url=f"https://example.com/{topic_slug}",
        )
        db_session.add(post)
        await db_session.flush()

        analysis_result = AnalysisResult(
            post_id=post.id,
            sentiment_score_id=sentiment.id,
            urgency=urgency,
        )
        analysis_result.topics.append(topic)
        db_session.add(analysis_result)
        await db_session.flush()
        return analysis_result

    return _make

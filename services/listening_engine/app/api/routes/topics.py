"""
Topic analytics routes.

GET /api/topics/trending       — ranked topics by volume
GET /api/topics/priority-score — full taxonomy + raw signals for pauta-meta
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_trending_topics
from app.analysis.priority import get_priority_topics
from app.api.dependencies import CommonFilters, get_db
from app.api.schemas import MetaResponse, TopicsPriorityScoreResponse, TopicsTrendingResponse

router = APIRouter()


@router.get(
    "/trending",
    response_model=TopicsTrendingResponse,
    summary="Trending topics",
    description=(
        "Returns the most discussed municipal topics ranked by post count. "
        "Each entry includes sentiment breakdown (positive/neutral/negative) "
        "and count of high-urgency posts. Filterable by date range and platform."
    ),
)
async def trending_topics(
    limit: int = Query(10, ge=1, le=50, description="Max number of topics to return."),
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    data = await get_trending_topics(db, filters, limit=limit)
    return TopicsTrendingResponse(
        topics=data["topics"],
        total_classified=data["total_classified"],
        meta=MetaResponse(
            generated_at=datetime.now(tz=timezone.utc),
            filters_applied=filters.as_dict(),
        ),
    )


@router.get(
    "/priority-score",
    response_model=TopicsPriorityScoreResponse,
    summary="Priority signals for pauta-meta",
    description=(
        "Returns **all** taxonomy topics with raw citizen-concern signals "
        "(volume, sentiment, urgency) for the pauta-meta Tuluá pipeline. "
        "Includes optional `reference_priority_index` and `pauta_tema` mapping — "
        "budget weighting and spend decisions remain in pauta-meta. "
        "Default lookback: 30 days when `from_date` / `to_date` are omitted."
    ),
)
async def priority_score(
    days: int = Query(
        30,
        ge=1,
        le=90,
        description="Lookback window in days (used when from_date/to_date not set).",
    ),
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    if filters.from_date is None and filters.to_date is None:
        now = datetime.now(tz=timezone.utc)
        filters.from_date = now - timedelta(days=days)
        filters.to_date = now

    data = await get_priority_topics(db, filters)
    meta_filters = {**filters.as_dict(), "days": days if "from_date" not in filters.as_dict() else None}

    return TopicsPriorityScoreResponse(
        topics=data["topics"],
        total_classified=data["total_classified"],
        tema_mapping_version=data["tema_mapping_version"],
        reference_index_formula=data["reference_index_formula"],
        sensitive_topic_slugs=data["sensitive_topic_slugs"],
        meta=MetaResponse(
            generated_at=datetime.now(tz=timezone.utc),
            filters_applied={k: v for k, v in meta_filters.items() if v is not None},
        ),
    )

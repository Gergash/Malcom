"""
GET /api/timeline
Sentiment trend over time — one data point per day.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_timeline
from app.api.dependencies import CommonFilters, get_db
from app.api.schemas import MetaResponse, TimelinePoint, TimelineResponse

router = APIRouter()


@router.get(
    "",
    response_model=TimelineResponse,
    summary="Sentiment timeline",
    description=(
        "Returns daily sentiment counts (positive / neutral / negative) "
        "and the net sentiment score for each day in the requested range. "
        "Designed for trend line charts in dashboards. "
        "Filterable by date range, platform and topic."
    ),
)
async def sentiment_timeline(
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    points = await get_timeline(db, filters)
    return TimelineResponse(
        timeline=[TimelinePoint(**p) for p in points],
        meta=MetaResponse(
            generated_at=datetime.now(tz=timezone.utc),
            filters_applied=filters.as_dict(),
        ),
    )

"""
GET /api/sources
Engagement metrics per registered source (Facebook page, news site, etc.).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_source_engagement
from app.api.dependencies import CommonFilters, get_db
from app.api.schemas import PaginatedResponse, SourceEngagement

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[SourceEngagement],
    summary="Source engagement",
    description=(
        "Returns engagement metrics per registered source: total posts, "
        "sentiment breakdown (positive/neutral/negative), high-urgency count, "
        "average confidence and net sentiment score. "
        "Sorted by post count descending. Paginated."
    ),
)
async def source_engagement(
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    data = await get_source_engagement(db, filters)
    return PaginatedResponse.build(
        data=[SourceEngagement(**item) for item in data["items"]],
        total=data["total"],
        page=filters.page,
        page_size=filters.page_size,
    )

"""
GET /api/sentiment/summary
Overall sentiment score with platform breakdown and optional filters.
"""
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_sentiment_summary
from app.api.dependencies import CommonFilters, get_db
from app.api.schemas import MetaResponse, SentimentSummaryResponse

router = APIRouter()


@router.get(
    "/summary",
    response_model=SentimentSummaryResponse,
    summary="Overall sentiment summary",
    description=(
        "Returns aggregate sentiment counts (positive / neutral / negative), "
        "net sentiment score in [-1, 1], percentage breakdown and per-platform split. "
        "Filterable by date range, platform and topic."
    ),
)
async def sentiment_summary(
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    data = await get_sentiment_summary(db, filters)
    return SentimentSummaryResponse(
        summary=data["summary"],
        by_platform=data["by_platform"],
        meta=MetaResponse(
            generated_at=datetime.now(tz=timezone.utc),
            filters_applied=filters.as_dict(),
        ),
    )

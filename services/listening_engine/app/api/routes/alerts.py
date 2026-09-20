"""
GET /api/alerts
High-urgency, negative-sentiment posts — the early-warning feed.
"""
import math
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_alerts
from app.api.dependencies import CommonFilters, get_db
from app.api.schemas import AlertItem, PaginatedResponse

router = APIRouter()

_URGENCY_CHOICES = {"high", "medium"}


@router.get(
    "",
    response_model=PaginatedResponse[AlertItem],
    summary="High-urgency alerts",
    description=(
        "Returns posts flagged as high-urgency AND negative-sentiment, "
        "ordered by recency. These are the critical signals for municipal decision-making. "
        "Supports pagination, date range, platform and topic filters."
    ),
)
async def list_alerts(
    urgency: List[str] = Query(
        ["high"],
        description="Urgency levels to include. Options: high, medium.",
    ),
    filters: CommonFilters = Depends(),
    db: AsyncSession = Depends(get_db),
):
    # Validate urgency values
    levels = [u for u in urgency if u in _URGENCY_CHOICES] or ["high"]
    data = await get_alerts(db, filters, urgency_levels=levels)

    return PaginatedResponse.build(
        data=[AlertItem(**item) for item in data["items"]],
        total=data["total"],
        page=filters.page,
        page_size=filters.page_size,
    )

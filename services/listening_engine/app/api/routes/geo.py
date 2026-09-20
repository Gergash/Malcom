"""
GET /api/geo/comuna-sentiment
Aggregate sentiment for texts that mention a Tuluá barrio or Comuna N.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.geo_aggregates import get_comuna_sentiment
from app.api.dependencies import get_db
from app.api.schemas import ComunaSentimentResponse, MetaResponse

router = APIRouter()


@router.get(
    "/comuna-sentiment",
    response_model=ComunaSentimentResponse,
    summary="Sentiment by Tuluá comuna (geo proxy)",
    description=(
        "Scans posts and comments for barrio/comuna mentions using "
        "`config/equivalencia_barrio_comuna.csv`. Only matched texts contribute. "
        "Does **not** invent geo coverage — check `coverage.choropleth_completo_recomendado` "
        "before painting a full 10-color map."
    ),
)
async def comuna_sentiment(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days."),
    from_date: Optional[datetime] = Query(None, description="Override start (ISO 8601)."),
    to_date: Optional[datetime] = Query(None, description="Override end (ISO 8601)."),
    n_min: int = Query(15, ge=1, le=500, description="Min sample per comuna for 'suficiente'."),
    include_comments: bool = Query(True, description="Include persisted comments in the scan."),
    db: AsyncSession = Depends(get_db),
) -> ComunaSentimentResponse:
    now = datetime.now(tz=timezone.utc)
    end = to_date or now
    start = from_date or (end - timedelta(days=days))

    data = await get_comuna_sentiment(
        db,
        from_date=start,
        to_date=end,
        n_min=n_min,
        include_comments=include_comments,
    )
    return ComunaSentimentResponse(
        comunas=data["comunas"],
        signals_total=data["signals_total"],
        signals_sample=data["signals_sample"],
        coverage=data["coverage"],
        advertencia=data["advertencia"],
        meta=MetaResponse(
            generated_at=now,
            filters_applied={
                "days": days,
                "from_date": start.isoformat(),
                "to_date": end.isoformat(),
                "n_min": n_min,
                "include_comments": include_comments,
            },
        ),
    )

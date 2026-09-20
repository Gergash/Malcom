"""Posts API: list and filter scraped content."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.database import get_db
from app.storage.models.posts import Post

router = APIRouter()


@router.get("")
async def list_posts(
    platform: Optional[str] = Query(None),
    source_id: Optional[int] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List posts with optional filters (platform, source_id, date range)."""
    q = select(Post).order_by(Post.scraped_at.desc()).limit(limit)
    if platform:
        q = q.where(Post.platform == platform)
    if source_id is not None:
        q = q.where(Post.source_id == source_id)
    if from_date:
        q = q.where(Post.posted_at >= from_date)
    if to_date:
        q = q.where(Post.posted_at <= to_date)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "source_id": r.source_id,
            "platform": r.platform,
            "text": (r.text or "")[:500],
            "url": r.url,
            "posted_at": r.posted_at,
            "sentiment_label": r.cached_sentiment_label,
        }
        for r in rows
    ]

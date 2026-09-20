"""
FastAPI shared dependencies.

- get_db: async DB session (re-exported from storage.database)
- CommonFilters: reusable query parameter group (date range, platform, topic, pagination)
- require_webhook_rate_limit: dependency that returns 429 when rate limited
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query, status

# Re-export so routes can import get_db from one place
from app.storage.database import get_db  # noqa: F401


def require_webhook_rate_limit(endpoint: str):
    """Return a dependency that raises 429 if webhook rate limit exceeded."""
    async def _check():
        from app.core.rate_limiter import check_webhook_rate_limit
        if not check_webhook_rate_limit(endpoint):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
            )
    return _check


class CommonFilters:
    """
    Reusable dependency injected into analytics endpoints.
    Encapsulates date range, platform, topic and pagination params.

    Usage in route:
        @router.get(...)
        async def endpoint(filters: CommonFilters = Depends()):
            ...
    """

    def __init__(
        self,
        from_date: Optional[datetime] = Query(
            None,
            description="Start of date range (ISO 8601). Filters on posted_at.",
            example="2026-01-01T00:00:00",
        ),
        to_date: Optional[datetime] = Query(
            None,
            description="End of date range (ISO 8601). Inclusive.",
            example="2026-03-13T23:59:59",
        ),
        platform: Optional[str] = Query(
            None,
            description="Filter by platform: facebook, instagram, twitter, news.",
            example="facebook",
        ),
        topic: Optional[str] = Query(
            None,
            description="Filter by topic slug: security, taxes, public_services, infrastructure, corruption, public_administration, other.",
            example="infrastructure",
        ),
        page: int = Query(1, ge=1, description="Page number (1-based)."),
        page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)."),
        cursor: Optional[str] = Query(None, description="Cursor for keyset pagination (more efficient at scale)."),
    ):
        self.from_date = from_date
        self.to_date = to_date
        self.platform = platform
        self.topic = topic
        self.page = page
        self.page_size = page_size
        self.cursor = cursor

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def as_dict(self) -> dict:
        """Serialise active filters for response metadata."""
        return {
            k: str(v) if isinstance(v, datetime) else v
            for k, v in {
                "from_date": self.from_date,
                "to_date": self.to_date,
                "platform": self.platform,
                "topic": self.topic,
            }.items()
            if v is not None
        }

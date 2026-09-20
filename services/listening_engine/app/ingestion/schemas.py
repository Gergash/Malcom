"""
Normalized output schema for scraped content.
All scrapers must return a list of objects matching this structure for NLP processing.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ScrapedItem(BaseModel):
    """Single item returned by any scraper. Ready for NLP pipeline."""

    source: str = Field(..., description="Human-readable source name (e.g. page title, site name)")
    platform: str = Field(..., description="One of: facebook, facebook_group, instagram, twitter, news")
    text: str = Field(..., description="Main post/article text content")
    date: Optional[datetime] = Field(default=None, description="Publication or scrape date")
    url: str = Field(..., description="Canonical URL of the post/article")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


def scraped_item_to_json(item: ScrapedItem) -> dict:
    """Serialize to JSON-friendly dict for storage/queue."""
    return item.model_dump(mode="json")

"""
Output schema for processed records.
ProcessedRecord is what process_record() returns and what gets persisted.
"""
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

TopicLabel = Literal[
    "security",
    "taxes",
    "public_services",
    "infrastructure",
    "corruption",
    "public_administration",
    "other",
]
SentimentLabel = Literal["positive", "neutral", "negative"]
UrgencyLabel = Literal["low", "medium", "high"]


class ProcessedRecord(BaseModel):
    """Fully classified record ready for storage and dashboard consumption."""

    text: str = Field(..., description="Cleaned text used for classification")
    original_text: str = Field(..., description="Raw text as received from the scraper")
    source: str = Field(..., description="Source name (page, site, profile)")
    platform: Optional[str] = Field(default=None)
    url: Optional[str] = Field(default=None)
    language: str = Field(..., description="ISO 639-1 code, e.g. 'es'")
    topic: TopicLabel
    sentiment: SentimentLabel
    urgency: UrgencyLabel
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime = Field(..., description="UTC timestamp of processing")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

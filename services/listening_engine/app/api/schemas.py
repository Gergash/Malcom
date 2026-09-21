"""
Response schemas for the analytics API.
All endpoints use these Pydantic models so FastAPI generates accurate OpenAPI docs.
"""
from datetime import date, datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Shared wrappers
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    total: int = Field(..., description="Total matching records (before pagination)")
    page: int
    page_size: int
    pages: int = Field(..., description="Total number of pages")

    @classmethod
    def build(cls, data: List[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        import math
        return cls(
            data=data,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 1,
        )


class MetaResponse(BaseModel):
    """Envelope with metadata for non-paginated endpoints."""
    generated_at: datetime
    filters_applied: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# GET /sentiment/summary
# ---------------------------------------------------------------------------

class SentimentBreakdown(BaseModel):
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    total: int = 0
    score: float = Field(
        0.0,
        description="Net sentiment score: (positive − negative) / total. Range −1 to 1.",
        ge=-1.0,
        le=1.0,
    )
    positive_pct: float = Field(0.0, description="% positive posts")
    negative_pct: float = Field(0.0, description="% negative posts")
    neutral_pct: float = Field(0.0, description="% neutral posts")


class SentimentSummaryResponse(BaseModel):
    summary: SentimentBreakdown
    by_platform: Dict[str, SentimentBreakdown] = Field(
        default_factory=dict,
        description="Sentiment breakdown per platform",
    )
    meta: MetaResponse


# ---------------------------------------------------------------------------
# GET /topics/trending
# ---------------------------------------------------------------------------

class TopicTrend(BaseModel):
    slug: str = Field(..., description="Topic identifier, e.g. 'infrastructure'")
    name: str
    count: int = Field(..., description="Number of posts classified under this topic")
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    urgency_high: int = Field(0, description="Posts with high urgency in this topic")
    share_pct: float = Field(0.0, description="Percentage of total classified posts")


class TopicsTrendingResponse(BaseModel):
    topics: List[TopicTrend]
    total_classified: int = Field(..., description="Total posts with a topic assigned")
    meta: MetaResponse


# ---------------------------------------------------------------------------
# GET /topics/priority-score  (pauta-meta integration)
# ---------------------------------------------------------------------------

class TopicPriorityItem(BaseModel):
    slug: str
    name: str
    count: int = 0
    share_pct: float = 0.0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    negative_pct: float = Field(0.0, description="% negative within this topic")
    urgency_high: int = 0
    urgency_high_pct: float = Field(0.0, description="% high-urgency within this topic")
    sentiment_score: float = Field(
        0.0,
        description="Net sentiment (positive − negative) / count, range −1 to 1",
        ge=-1.0,
        le=1.0,
    )
    pauta_tema: Optional[str] = Field(
        None,
        description="Mapped pauta-meta TEMA, or null when no paid-budget equivalent",
    )
    requires_human_review: bool = Field(
        False,
        description="True for sensitive topics (corruption/security) with negative or high-urgency signal",
    )
    reference_priority_index: float = Field(
        0.0,
        ge=0.0,
        le=100.0,
        description="Non-binding concern index; budget weighting stays in pauta-meta",
    )


class TopicsPriorityScoreResponse(BaseModel):
    topics: List[TopicPriorityItem]
    total_classified: int
    tema_mapping_version: str
    reference_index_formula: str
    sensitive_topic_slugs: List[str]
    meta: MetaResponse


# ---------------------------------------------------------------------------
# GET /alerts
# ---------------------------------------------------------------------------

class AlertItem(BaseModel):
    id: int
    text: str = Field(..., description="First 400 chars of post text")
    platform: str
    source_name: Optional[str] = None
    url: str
    posted_at: Optional[datetime] = None
    urgency: str
    sentiment: str
    confidence: Optional[float] = None
    topic: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /timeline
# ---------------------------------------------------------------------------

class TimelinePoint(BaseModel):
    date: date
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    total: int = 0
    score: float = Field(0.0, description="Net sentiment score for this day")
    avg_confidence: Optional[float] = None


class TimelineResponse(BaseModel):
    timeline: List[TimelinePoint]
    meta: MetaResponse


# ---------------------------------------------------------------------------
# GET /sources
# ---------------------------------------------------------------------------

class SourceEngagement(BaseModel):
    source_id: int
    name: str
    platform: str
    post_count: int
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    high_urgency: int = Field(0, description="Posts with high urgency")
    avg_confidence: Optional[float] = None
    score: float = Field(0.0, description="Net sentiment score for this source")
    last_scraped_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Webhook schemas
# ---------------------------------------------------------------------------

class TriggerScrapingRequest(BaseModel):
    """Optional body for POST /webhooks/trigger-scraping."""
    note: Optional[str] = Field(None, description="Optional note for audit log.")


class TriggerScrapingResponse(BaseModel):
    status: str = Field(..., description="queued | error")
    task_id: Optional[str] = Field(None, description="Celery task ID for status polling.")
    message: str
    queued_at: datetime
    sources_count: int = Field(0, description="Number of active sources that will be scraped.")


class ScrapeStatusResponse(BaseModel):
    """Estado de una tarea Celery de scraping (para barra de progreso)."""
    task_id: str
    state: str = Field(..., description="PENDING | STARTED | PROGRESS | SUCCESS | FAILURE | …")
    phase: str = Field("unknown", description="queued | scraping | processing | done | error")
    percent: int = Field(0, ge=0, le=100)
    done: int = 0
    total: int = 0
    new_posts: int = 0
    detail: str = ""
    process_task_id: Optional[str] = None
    ready: bool = False


class ReportRequest(BaseModel):
    """Body for POST /webhooks/generate-report."""
    from_date: Optional[datetime] = Field(None, description="Start of report period (ISO 8601).")
    to_date: Optional[datetime] = Field(None, description="End of report period (ISO 8601). Defaults to now.")
    alert_limit: int = Field(10, ge=1, le=50, description="Max critical alerts to include.")


class FormattedBlocks(BaseModel):
    telegram:   str = Field(..., description="Telegram-ready Markdown message.")
    gpt_prompt: str = Field(..., description="Structured prompt for Custom GPT / Claude.")
    plain_text: str = Field(..., description="Plain text summary for logging or simple bots.")


class ThermometerBlock(BaseModel):
    score:          float
    trend:          str
    trend_label:    str
    label:          str
    interpretation: str
    top_concerns:   List[str] = []


class SentimentBlock(BaseModel):
    positive:     int = 0
    neutral:      int = 0
    negative:     int = 0
    total:        int = 0
    score:        float = 0.0
    positive_pct: float = 0.0
    neutral_pct:  float = 0.0
    negative_pct: float = 0.0


class IssueItem(BaseModel):
    rank:            int
    topic:           str
    label:           str
    mentions:        int
    positive:        int = 0
    neutral:         int = 0
    negative:        int = 0
    urgency_high:    int = 0
    sentiment_score: float = 0.0
    share_pct:       float = 0.0


class SpikeItem(BaseModel):
    date:               str
    total_posts:        int
    volume_vs_avg:      float
    sentiment_score:    float
    dominant_sentiment: str
    positive:           int = 0
    neutral:            int = 0
    negative:           int = 0
    reasons:            List[str] = []


class ReportPeriod(BaseModel):
    from_:  str = Field(..., alias="from")
    to:     str
    label:  str

    class Config:
        populate_by_name = True


class ReportResponse(BaseModel):
    """Full report returned by /webhooks/generate-report and /webhooks/weekly-thermometer."""
    report_id:       str
    generated_at:    datetime
    period:          Dict[str, Any]
    thermometer:     ThermometerBlock
    sentiment:       SentimentBlock
    top_issues:      List[IssueItem]
    recent_spikes:   List[SpikeItem]
    critical_alerts: List[AlertItem]
    alert_count:     int
    formatted:       FormattedBlocks


class LatestAlertsResponse(BaseModel):
    """Response for GET /webhooks/latest-alerts."""
    count:      int
    total:      int
    fetched_at: datetime
    alerts:     List[AlertItem]
    formatted:  FormattedBlocks


# ---------------------------------------------------------------------------
# GET /api/geo/comuna-sentiment
# ---------------------------------------------------------------------------

class ComunaBucket(BaseModel):
    comuna_id: int
    comuna_label: str
    n: int = 0
    n_posts: int = 0
    n_comments: int = 0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    unknown: int = 0
    classified: int = 0
    sentiment_score: Optional[float] = None
    banda: str = Field(
        ...,
        description="sin_dato | muestra_baja | alta | media | baja",
    )
    muestra_suficiente: bool = False
    n_min: int = 15
    match_ejemplos: List[str] = Field(default_factory=list)


class GeoCoverage(BaseModel):
    comunas_con_dato: int
    comunas_sobre_minimo: int
    n_min_por_comuna: int
    choropleth_completo_recomendado: bool


class GeoSignalSample(BaseModel):
    item_id: int
    item_type: str
    comuna_id: int
    match_texto: Optional[str] = None
    match_tipo: Optional[str] = None
    confianza_geo: Optional[str] = None
    sentiment_label: Optional[str] = None
    posted_at: Optional[str] = None
    url: Optional[str] = None
    platform: Optional[str] = None


class ComunaSentimentResponse(BaseModel):
    comunas: List[ComunaBucket]
    signals_total: int
    signals_sample: List[GeoSignalSample] = Field(default_factory=list)
    coverage: GeoCoverage
    advertencia: str
    meta: MetaResponse


class BackfillCommentsRequest(BaseModel):
    limit: int = Field(500, ge=1, le=5000, description="Max posts to scan for metadata comments.")


class BackfillCommentsResponse(BaseModel):
    status: str
    scanned: int = 0
    inserted: int = 0
    message: str
    queued_at: datetime

"""
NLP pipeline orchestrator.

Entry points:
  process_record(record)  → ProcessedRecord   (single item, full pipeline)
  run_pipeline(items)     → List[dict]         (batch, backward-compatible)

Pipeline stages per record:
  0. sanitize_record()  – Ley 1581 privacy layer (PII removal before any storage/LLM call)
  1. clean_text()       – HTML / URL / whitespace cleanup
  2. detect_language()  – heuristic + LLM
  3. Combined LLM call  – topic + sentiment + urgency in one request (cost-efficient)
     └ fallback         – individual calls if combined response is malformed
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from app.processing._llm import llm_complete_json
from app.processing.language import detect_language
from app.processing.normalizer import clean_text
from app.processing.privacy import sanitize_record
from app.processing.schemas import (
    ProcessedRecord,
    SentimentLabel,
    TopicLabel,
    UrgencyLabel,
)
from app.processing.sentiment import classify_sentiment
from app.processing.topics import classify_topic
from app.processing.urgency import classify_urgency

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Combined prompt — one API call for topic + sentiment + urgency
# ---------------------------------------------------------------------------

_COMBINED_SYSTEM = """You are a social-listening classifier for the Comando General de las Fuerzas Militares de Colombia (COMES / CGFM) and Plan Ayacucho monitoring.
Analyze public posts, news and conversations about the Armed Forces, Defense sector and institutional campaigns.
Return ONLY a valid JSON object — no explanation, no markdown.

OUTPUT FORMAT:
{
  "topic":      "<topic>",
  "sentiment":  "<sentiment>",
  "urgency":    "<urgency>",
  "confidence": <float 0.0-1.0>
}

TOPIC — choose exactly one:
- security              : defense ops, public order, armed conflict mentions, military security, threats
- taxes                 : defense budget, fiscal debates tied to the military sector (rare)
- public_services       : institutional services to civilians, recruitment support, military social programs
- infrastructure        : military infrastructure, bases, logistics, equipment, obras institucionales
- corruption            : corruption, scandals, transparency issues involving defense/military actors
- public_administration : Comando General, institutional communications, Plan Ayacucho, doctrine, governance
- other                 : anything not clearly fitting the above

SENTIMENT — toward the Armed Forces / Comando General / Plan Ayacucho / Sector Defensa:
- positive : support, praise, trust, recognition
- neutral  : informational, factual, balanced reporting (imparcial)
- negative : criticism, rejection, alarm, hostility

URGENCY — choose exactly one:
- high   : crisis, security emergency, viral hostile narrative requiring same-day attention
- medium : emerging reputational issue, recurring criticism, attention within days
- low    : routine coverage, minor or historical commentary

CONFIDENCE: overall certainty (0.0–1.0)."""

_VALID_TOPICS     = {"security","taxes","public_services","infrastructure","corruption","public_administration","other"}
_VALID_SENTIMENTS = {"positive", "neutral", "negative"}
_VALID_URGENCIES  = {"low", "medium", "high"}


async def _classify_combined(
    text: str,
) -> Optional[tuple[TopicLabel, SentimentLabel, UrgencyLabel, float]]:
    """
    Single LLM call returning (topic, sentiment, urgency, confidence).
    Returns None if the response is missing or contains invalid values.
    """
    data = await llm_complete_json(_COMBINED_SYSTEM, text, max_tokens=120)
    if not data:
        return None

    topic     = str(data.get("topic",     "")).lower().strip()
    sentiment = str(data.get("sentiment", "")).lower().strip()
    urgency   = str(data.get("urgency",   "")).lower().strip()

    if topic not in _VALID_TOPICS or sentiment not in _VALID_SENTIMENTS or urgency not in _VALID_URGENCIES:
        logger.warning("combined_classification_invalid", topic=topic, sentiment=sentiment, urgency=urgency)
        return None

    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    return topic, sentiment, urgency, confidence  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_record(record: Dict[str, Any]) -> ProcessedRecord:
    """
    Run the full NLP pipeline on a single scraped record.

    Args:
        record: dict with at least 'text' and 'source'.
                Optional: 'platform', 'url', 'metadata'.

    Returns:
        ProcessedRecord with language, topic, sentiment, urgency and confidence.
    """
    # Stage 0 — privacy (Ley 1581): remove PII before any LLM call or storage
    record, privacy_report = sanitize_record(record)
    if privacy_report.has_pii:
        logger.info(
            "privacy_pii_removed",
            mentions=privacy_report.mentions_removed,
            profile_urls=privacy_report.profile_urls_removed,
            emails=privacy_report.emails_removed,
            phones=privacy_report.phones_removed,
            cedulas=privacy_report.cedulas_removed,
            doc_numbers=privacy_report.doc_numbers_removed,
            contact_refs=privacy_report.contact_refs_removed,
            metadata_keys=privacy_report.metadata_keys_cleared,
        )

    original_text: str = record.get("text") or ""
    source: str        = record.get("source") or ""
    platform           = record.get("platform")
    url                = record.get("url")
    metadata: dict     = record.get("metadata") or {}

    log = logger.bind(source=source, platform=platform)

    # Stage 1 — clean
    cleaned = clean_text(original_text)

    # Stage 2 — language
    language = await detect_language(cleaned or original_text)

    # Stage 3 — classify
    topic:      TopicLabel     = "other"
    sentiment:  SentimentLabel = "neutral"
    urgency:    UrgencyLabel   = "low"
    confidence: float          = 0.0

    if cleaned:
        combined = await _classify_combined(cleaned)
        if combined:
            topic, sentiment, urgency, confidence = combined
            log.info("pipeline_ok", topic=topic, sentiment=sentiment, urgency=urgency, confidence=confidence)
        else:
            # Fallback: three independent calls
            log.warning("pipeline_combined_fallback")
            topic,    t_conf = await classify_topic(cleaned)
            s_dict           = await classify_sentiment(cleaned)
            sentiment        = s_dict["score"]
            s_conf           = s_dict.get("confidence", 0.0)
            urgency,  u_conf = await classify_urgency(cleaned)
            confidence       = round((t_conf + s_conf + u_conf) / 3, 4)
            log.info("pipeline_fallback_ok", topic=topic, sentiment=sentiment, urgency=urgency, confidence=confidence)
    else:
        log.warning("pipeline_empty_text", original_length=len(original_text))

    return ProcessedRecord(
        text=cleaned or original_text,
        original_text=original_text,
        source=source,
        platform=platform,
        url=url,
        language=language,
        topic=topic,
        sentiment=sentiment,
        urgency=urgency,
        confidence=confidence,
        timestamp=datetime.now(tz=timezone.utc),
        metadata=metadata,
    )


async def run_pipeline(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Backward-compatible batch entry point used by the scheduler.
    Runs process_record() on every item and returns enriched dicts.
    """
    results = []
    for item in items:
        record = await process_record(item)
        out = {
            **item,
            "normalized_text":  record.text,
            "language":         record.language,
            "sentiment_score":  record.sentiment,
            "sentiment_label":  record.sentiment.capitalize(),
            "sentiment_confidence": record.confidence,
            "topic":            record.topic,
            "topics":           [record.topic],          # legacy field
            "urgency":          record.urgency,
            "confidence":       record.confidence,
            "processed_at":     record.timestamp.isoformat(),
        }
        results.append(out)
    return results

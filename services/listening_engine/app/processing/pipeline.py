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

_COMBINED_SYSTEM = """You are a municipal affairs classifier for Tuluá, Valle del Cauca, Colombia.
Analyze citizen-generated text about local government and public services.
Return ONLY a valid JSON object — no explanation, no markdown.

OUTPUT FORMAT:
{
  "topic":      "<topic>",
  "sentiment":  "<sentiment>",
  "urgency":    "<urgency>",
  "confidence": <float 0.0-1.0>
}

TOPIC — choose exactly one:
- security              : crime, violence, theft, assault, police, public safety, gangs
- taxes                 : property tax, municipal fees, fines, billing, cobros, impuestos
- public_services       : water, sewage, garbage, public transport, hospitals, schools, electricity
- infrastructure        : roads, potholes, bridges, parks, sidewalks, street lighting, obras, vías
- corruption            : bribes, embezzlement, nepotism, misuse of funds, lack of transparency
- public_administration : permits, bureaucracy, response times, officials, government programs, PQRS
- other                 : anything not clearly fitting the above categories

SENTIMENT — choose exactly one:
- positive : satisfaction, praise, gratitude, improvement noted
- neutral  : informational, question, balanced or factual statement
- negative : complaint, criticism, dissatisfaction, anger, demand

URGENCY — choose exactly one:
- high   : immediate danger, complete service failure, emergency, same-day action required
- medium : ongoing daily-life problem, recurring issue, attention needed within days
- low    : general feedback, suggestion, minor or cosmetic issue

CONFIDENCE: overall certainty across all three classifications (0.0 = uncertain, 1.0 = certain)."""

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

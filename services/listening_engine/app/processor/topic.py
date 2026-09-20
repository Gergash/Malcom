"""
Topic classification for a single text record.
Returns one of the seven canonical municipal topics.
"""
import structlog

from app.processor._llm import llm_complete_json
from app.processor.schemas import TopicLabel

logger = structlog.get_logger(__name__)

_VALID_TOPICS = {
    "security",
    "taxes",
    "public_services",
    "infrastructure",
    "corruption", 
    "public_administration",
    "other",
}

_DEFAULT: TopicLabel = "other"

_SYSTEM = """You are a municipal affairs classifier for Tuluá, Valle del Cauca, Colombia.
Classify the citizen text into exactly ONE topic.

TOPIC DEFINITIONS:
- security: crime, violence, theft, assault, police, public safety, gangs, homicides
- taxes: property tax, municipal fees, fines, billing, tax collection, cobros, impuestos
- public_services: water supply, sewage, garbage collection, public transport, hospitals, schools, electricity, acueducto, alcantarillado
- infrastructure: roads, potholes, bridges, parks, sidewalks, street lighting, construction, obras, vías, andenes
- corruption: bribes, embezzlement, nepotism, misuse of public funds, lack of transparency, irregularidades
- public_administration: permits, bureaucracy, response times, officials conduct, government programs, PQRS, trámites
- other: anything not fitting the categories above

Return ONLY a JSON object:
{"topic": "<topic>", "confidence": <0.0-1.0>}
No explanation. No markdown."""


async def classify_topic(text: str) -> tuple[TopicLabel, float]:
    """
    Classify the municipal topic of *text*.

    Returns:
        (topic_label, confidence) — defaults to ('other', 0.0) on error.
    """
    if not text or not text.strip():
        return _DEFAULT, 0.0

    try:
        data = await llm_complete_json(_SYSTEM, text, max_tokens=60)
        if data:
            topic = str(data.get("topic", "")).lower().strip()
            if topic in _VALID_TOPICS:
                confidence = float(data.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                return topic, confidence  # type: ignore[return-value]
    except Exception:
        logger.warning("classify_topic_failed", text_snippet=text[:80])

    return _DEFAULT, 0.0

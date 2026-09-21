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

_SYSTEM = """You are a topic classifier for social listening of Colombia's Armed Forces (COMES / CGFM) and Plan Ayacucho.
Classify the text into exactly ONE topic.

TOPIC DEFINITIONS:
- security: defense, public order, threats, operations, military security
- taxes: defense budget / fiscal debate tied to the military sector
- public_services: institutional services to civilians, recruitment support, military social programs
- infrastructure: bases, logistics, equipment, institutional obras
- corruption: corruption, scandals, transparency involving defense/military actors
- public_administration: Comando General, institutional comms, Plan Ayacucho, doctrine, governance
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

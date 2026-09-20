"""
Topic classification using the shared LLM client.
Replaces free-form list extraction with a single canonical label
from the seven defined municipal topics.
The old extract_topics() alias is preserved for backward compatibility.
"""
import structlog

from app.processing._llm import llm_complete_json
from app.processing.schemas import TopicLabel

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
Classify the citizen text into exactly ONE topic from the list below.

TOPIC DEFINITIONS:
- security              : crime, violence, theft, assault, police, public safety, gangs
- taxes                 : property tax, municipal fees, fines, billing, cobros, impuestos
- public_services       : water, sewage, garbage, public transport, hospitals, schools, electricity
- infrastructure        : roads, potholes, bridges, parks, sidewalks, street lighting, obras, vías
- corruption            : bribes, embezzlement, nepotism, misuse of public funds, lack of transparency
- public_administration : permits, bureaucracy, response times, officials, government programs, PQRS
- other                 : anything not clearly fitting the categories above

Return ONLY a JSON object — no explanation, no markdown:
{"topic": "<topic>", "confidence": <0.0-1.0>}"""


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
                confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
                return topic, confidence  # type: ignore[return-value]
    except Exception:
        logger.warning("classify_topic_failed", snippet=text[:80])

    return _DEFAULT, 0.0


async def extract_topics(text: str) -> list[str]:
    """
    Backward-compatible alias used by the old run_pipeline().
    Returns a single-element list with the canonical topic label.
    """
    topic, _ = await classify_topic(text)
    return [topic]

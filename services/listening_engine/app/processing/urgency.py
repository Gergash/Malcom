"""
Urgency classification for scraped civic text.
Measures how urgently the described situation demands municipal action.
New capability — no equivalent existed in the original processing layer.
"""
import structlog

from app.processing._llm import llm_complete_json
from app.processing.schemas import UrgencyLabel

logger = structlog.get_logger(__name__)

_VALID = {"low", "medium", "high"}
_DEFAULT: UrgencyLabel = "low"

_SYSTEM = """You are an urgency classifier for a municipal early-warning system in Tuluá, Colombia.
Assess how urgently the described situation requires government action.

URGENCY DEFINITIONS:
- high   : immediate danger to life or property, complete service failure (no water, road collapse,
           active violence), emergency requiring same-day response
- medium : ongoing problem clearly affecting daily life (recurring outages, unsafe road, chronic
           service failure), needs attention within a few days
- low    : general feedback, suggestion, minor inconvenience, long-term or cosmetic issue,
           historical or anecdotal complaint

Return ONLY a JSON object — no explanation, no markdown:
{"urgency": "<urgency>", "confidence": <0.0-1.0>}"""


async def classify_urgency(text: str) -> tuple[UrgencyLabel, float]:
    """
    Classify how urgently *text* demands municipal action.

    Returns:
        (urgency_label, confidence) — defaults to ('low', 0.0) on error.
    """
    if not text or not text.strip():
        return _DEFAULT, 0.0

    try:
        data = await llm_complete_json(_SYSTEM, text, max_tokens=60)
        if data:
            urgency = str(data.get("urgency", "")).lower().strip()
            if urgency in _VALID:
                confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
                return urgency, confidence  # type: ignore[return-value]
    except Exception:
        logger.warning("classify_urgency_failed", snippet=text[:80])

    return _DEFAULT, 0.0

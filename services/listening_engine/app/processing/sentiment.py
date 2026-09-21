"""
Sentiment classification using the shared LLM client.
Returns structured JSON with label and confidence instead of a plain string.
Replaces the original single-provider, no-retry, no-confidence stub.
"""
import structlog

from app.processing._llm import llm_complete_json
from app.processing.schemas import SentimentLabel

logger = structlog.get_logger(__name__)

_VALID = {"positive", "neutral", "negative"}
_DEFAULT: SentimentLabel = "neutral"

_SYSTEM = """You are a sentiment classifier for public discourse about Colombia's Armed Forces, the Comando General (COMES/CGFM), Plan Ayacucho and the Defense sector.
Classify sentiment toward those institutions/campaigns (not toward unrelated municipal topics).

SENTIMENT DEFINITIONS:
- positive : support, praise, trust, recognition, constructive endorsement
- neutral  : informational, factual, balanced / imparcial reporting
- negative : criticism, rejection, hostility, alarm, discredit

Return ONLY a JSON object — no explanation, no markdown:
{"sentiment": "<sentiment>", "confidence": <0.0-1.0>}"""


async def classify_sentiment(text: str) -> dict:
    """
    Classify sentiment of *text* toward the municipality.

    Returns:
        dict with keys 'score' (label), 'label' (capitalised), 'confidence'.
        Kept backward-compatible with the old {'score', 'label'} shape used
        by pipeline.run_pipeline().
    """
    if not text or not text.strip():
        return {"score": "neutral", "label": "Neutral", "confidence": 0.0}

    try:
        data = await llm_complete_json(_SYSTEM, text, max_tokens=60)
        if data:
            label = str(data.get("sentiment", "")).lower().strip()
            if label in _VALID:
                confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
                return {
                    "score": label,
                    "label": label.capitalize(),
                    "confidence": confidence,
                }
    except Exception:
        logger.warning("classify_sentiment_failed", snippet=text[:80])

    return {"score": "neutral", "label": "Neutral", "confidence": 0.0}

"""
Language detection for scraped text.
Uses a fast Spanish-word heuristic (zero API cost) first;
falls back to LLM for short or ambiguous texts.
Default is 'es' — the system is tuned for Tuluá, Colombia.
"""
import re

import structlog

from app.processing._llm import llm_complete

logger = structlog.get_logger(__name__)

# High-frequency Spanish function words and Tuluá-specific terms.
_SPANISH_MARKERS = frozenset({
    "de", "la", "el", "en", "y", "a", "que", "los", "las", "se",
    "con", "del", "por", "un", "una", "para", "es", "no", "al",
    "como", "pero", "más", "este", "esta", "muy", "hay", "fue",
    "su", "sus", "todo", "también", "está", "son", "han", "lo",
    "le", "nos", "si", "ya", "me", "mi", "tu", "te", "yo",
    "cuando", "porque", "sobre", "hasta", "entre", "donde",
    "ahora", "siempre", "puede", "hacer", "tiene",
    "municipal", "alcaldía", "tuluá", "ciudad", "barrio",
})

_WORD = re.compile(r"\b\w+\b")
_HEURISTIC_THRESHOLD = 0.08   # ≥8 % Spanish markers → return 'es' immediately
_MIN_CHARS_FOR_HEURISTIC = 30  # texts shorter than this go straight to LLM

_SYSTEM = (
    "Detect the language of the following text. "
    "Return ONLY the ISO 639-1 two-letter code in lowercase (e.g. es, en, pt, fr). "
    "No explanation, no punctuation."
)


async def detect_language(text: str) -> str:
    """
    Detect the language of *text*.

    Strategy:
      1. If text is long enough and contains ≥8 % Spanish marker words → 'es'.
      2. Otherwise call the LLM for a definitive 2-letter code.
      3. On any error → default 'es'.

    Returns:
        ISO 639-1 code string, e.g. 'es', 'en', 'pt'.
    """
    if not text or not text.strip():
        return "es"

    if len(text) >= _MIN_CHARS_FOR_HEURISTIC:
        words = _WORD.findall(text.lower())
        if words:
            score = sum(1 for w in words if w in _SPANISH_MARKERS) / len(words)
            if score >= _HEURISTIC_THRESHOLD:
                return "es"

    try:
        code = await llm_complete(_SYSTEM, text, max_tokens=5)
        code = code.strip().lower()[:2]
        if code.isalpha() and len(code) == 2:
            return code
    except Exception:
        logger.warning("language_detection_failed", snippet=text[:80])

    return "es"

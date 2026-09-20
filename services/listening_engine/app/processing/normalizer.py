"""
Text normalizer / cleaner for the NLP pipeline.
Replaces the original whitespace-only stub with full scraping-grade cleanup.
"""
import html
import re
import unicodedata
from typing import Optional

# Compiled patterns
_HTML_TAG      = re.compile(r"<[^>]+>")
_URL           = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION       = re.compile(r"@\w+")
_HASHTAG       = re.compile(r"#(\w+)")
_ZERO_WIDTH    = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]")
_REPEAT_PUNCT  = re.compile(r"([!?.,:;])\1{2,}")
_FANCY_QUOTES  = re.compile(r"[\u2018\u2019\u201c\u201d\u00ab\u00bb]")
_WHITESPACE    = re.compile(r"\s+")


def normalize_text(text: str, max_chars: Optional[int] = 8000) -> str:
    """
    Backward-compatible alias for clean_text() with a higher default cap.
    Used by the existing pipeline.run_pipeline() call chain.
    """
    return clean_text(text, max_chars=max_chars or 8000)


def clean_text(text: str, *, max_chars: int = 4000) -> str:
    """
    Full scraping-grade text cleaner for LLM classification.

    Steps:
      1. HTML entity decoding
      2. Strip HTML tags
      3. Remove URLs
      4. Remove @mentions; keep #hashtag as plain word
      5. Remove zero-width / invisible Unicode chars
      6. NFC normalisation
      7. Normalise fancy quotation marks to ASCII double-quote
      8. Collapse repeated punctuation  (!!!!! → !)
      9. Collapse whitespace
      10. Truncate to max_chars at word boundary

    Args:
        text: Raw scraped string.
        max_chars: Hard cap for LLM token budget.

    Returns:
        Cleaned string; empty string if input is falsy.
    """
    if not text or not isinstance(text, str):
        return ""

    text = html.unescape(text)
    text = _HTML_TAG.sub(" ", text)
    text = _URL.sub(" ", text)
    text = _MENTION.sub(" ", text)
    text = _HASHTAG.sub(r"\1", text)
    text = _ZERO_WIDTH.sub("", text)
    text = unicodedata.normalize("NFC", text)
    text = _FANCY_QUOTES.sub('"', text)
    text = _REPEAT_PUNCT.sub(r"\1", text)
    text = _WHITESPACE.sub(" ", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0]

    return text.strip()

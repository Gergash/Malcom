"""
Privacy protection preprocessing layer — Ley 1581 de 2012 compliance.

Colombian data protection law (Habeas Data — Ley 1581 de 2012 and Decreto 1377 de 2013)
establishes that personal data must be:
  - Collected for a specific, explicit and legitimate purpose (Art. 4.b)
  - Limited to what is necessary for that purpose (data minimisation, Art. 4.c)
  - Not stored in a way that permits identification beyond what the purpose requires (Art. 4.e)

This module implements data minimisation BEFORE any storage or LLM call:
  - @usernames and @mentions are removed (identifiers of social accounts)
  - Profile URLs / personal links are stripped (direct identifiers)
  - Phone numbers (Colombian and international formats) are redacted
  - Colombian cédulas de ciudadanía (CC), cédulas de extranjería (CE),
    NIT and passport references are redacted
  - E-mail addresses are redacted
  - WhatsApp / Telegram personal contact references are redacted
  - The `original_text` field (which would retain raw PII) is replaced with
    the sanitized text so that PII never reaches the database or the LLM.

Only the following data is persisted (Art. 4.b — specific purpose):
  - Cleaned text (opinion content without personal identifiers)
  - Publication date
  - Platform / source (aggregate, not profile-level)
  - URL of the public post (already public, not a personal identifier)
  - Topic, sentiment, urgency (derived classifications)

Audit trail: a PrivacyReport dataclass logs *what categories* of data were
removed (not the actual PII values) so the data controller can demonstrate
compliance without re-storing the sensitive data (Art. 9, 10).

References:
  - Ley 1581 de 2012: https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=49981
  - Decreto 1377 de 2013: https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=53646
  - SIC Circular Única — tratamiento de datos personales en redes sociales
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Compiled patterns  (order matters — apply most specific first)
# ---------------------------------------------------------------------------

# Colombian cédula: 6–10 digits optionally preceded by "CC", "C.C.", "cédula", etc.
_CEDULA = re.compile(
    r"\b(?:c\.?c\.?|cédula|cedula|c\.e\.?|nit|pasaporte)\s*[:\-]?\s*\d[\d\.\-]{5,12}\b",
    re.IGNORECASE,
)

# Standalone long digit sequences that look like document numbers (≥8 digits)
_DOC_NUMBER = re.compile(r"\b\d{8,12}\b")

# E-mail addresses
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b")

# Phone numbers: Colombian (3xx xxx xxxx, +57 …) and international (+nn …)
_PHONE = re.compile(
    r"(?:\+\d{1,3}[\s\-.]?)?"        # optional country code
    r"(?:\(?\d{1,4}\)?[\s\-.]?)?"    # optional area code
    r"\d{3}[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"  # main number
)

# @mentions (social-media usernames)
_MENTION = re.compile(r"@\w+")

# Profile / personal URLs — keep public news URLs but strip social profile paths
# e.g. facebook.com/username, instagram.com/user, twitter.com/user, tiktok.com/@user
_PROFILE_URL = re.compile(
    r"https?://(?:www\.)?(?:facebook|instagram|twitter|x|tiktok|linkedin|threads)\."
    r"[a-z]{2,}/(?:@?[\w.%-]{1,64}/?)",
    re.IGNORECASE,
)

# Generic URLs (fallback — remove remaining bare links)
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

# WhatsApp / Telegram contact references
_CONTACT_REF = re.compile(
    r"\b(?:escríbeme|contáctame|contactame|whatsapp|telegram|escribe)\b[^.!?\n]{0,80}",
    re.IGNORECASE,
)

# Collapse extra whitespace after replacements
_WHITESPACE = re.compile(r"\s{2,}")

# Replacement token (neutral, non-identifiable)
_REDACTED = "[DATO PERSONAL]"


# ---------------------------------------------------------------------------
# Audit dataclass
# ---------------------------------------------------------------------------

@dataclass
class PrivacyReport:
    """
    Records which *categories* of personal data were removed.
    Stored for audit purposes; no actual PII values are retained.
    Complies with Art. 9 Ley 1581 (documentation of data treatment decisions).
    """
    mentions_removed:      int = 0
    profile_urls_removed:  int = 0
    emails_removed:        int = 0
    phones_removed:        int = 0
    cedulas_removed:       int = 0
    doc_numbers_removed:   int = 0
    contact_refs_removed:  int = 0
    metadata_keys_cleared: List[str] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return (
            self.mentions_removed > 0
            or self.profile_urls_removed > 0
            or self.emails_removed > 0
            or self.phones_removed > 0
            or self.cedulas_removed > 0
            or self.doc_numbers_removed > 0
            or self.contact_refs_removed > 0
            or bool(self.metadata_keys_cleared)
        )


# ---------------------------------------------------------------------------
# Metadata keys that may carry PII — cleared before storage
# ---------------------------------------------------------------------------

_PII_METADATA_KEYS = frozenset({
    "author",
    "author_id",
    "user_id",
    "username",
    "display_name",
    "full_name",
    "profile_url",
    "profile_image",
    "avatar",
    "email",
    "phone",
    "location",
    "bio",
    "followers",     # indirectly identifies the account
    "following",
    "account_age",
    "verified",      # can narrow down identity
    "author_handle",
    "commenter",
    "commenter_id",
    "reply_to_user",
    "reply_to_id",
    "mentions",
    "tagged_users",
})


# ---------------------------------------------------------------------------
# Core sanitization function
# ---------------------------------------------------------------------------

def sanitize(text: str) -> tuple[str, PrivacyReport]:
    """
    Remove personal identifiers from a text string.

    Returns:
        (sanitized_text, PrivacyReport)

    The PrivacyReport records counts by category but never stores actual PII.
    Callers should log the PrivacyReport for audit, not the original text.

    Complies with:
      - Ley 1581/2012, Art. 4 (principios del tratamiento)
      - Decreto 1377/2013 (reglamentación del tratamiento)
    """
    if not text or not isinstance(text, str):
        return "", PrivacyReport()

    report = PrivacyReport()
    t = text

    # 1. Document numbers (cédulas, NIT, etc.) — most specific first
    matches = _CEDULA.findall(t)
    if matches:
        report.cedulas_removed = len(matches)
        t = _CEDULA.sub(_REDACTED, t)

    # 2. E-mail addresses
    matches = _EMAIL.findall(t)
    if matches:
        report.emails_removed = len(matches)
        t = _EMAIL.sub(_REDACTED, t)

    # 3. Profile URLs (social platforms) — before generic URL removal
    matches = _PROFILE_URL.findall(t)
    if matches:
        report.profile_urls_removed = len(matches)
        t = _PROFILE_URL.sub(_REDACTED, t)

    # 4. Generic remaining URLs
    t = _URL.sub("", t)

    # 5. @mentions
    matches = _MENTION.findall(t)
    if matches:
        report.mentions_removed = len(matches)
        t = _MENTION.sub("", t)

    # 6. Phone numbers (after email so +57xxx doesn't partially match email)
    matches = _PHONE.findall(t)
    # Filter: only flag if the candidate looks like a real phone (≥8 contiguous digits)
    real_phones = [m for m in matches if re.search(r"\d{7,}", m.replace(" ", "").replace("-", "").replace(".", ""))]
    if real_phones:
        report.phones_removed = len(real_phones)
        t = _PHONE.sub("", t)

    # 7. WhatsApp / Telegram contact references
    matches = _CONTACT_REF.findall(t)
    if matches:
        report.contact_refs_removed = len(matches)
        t = _CONTACT_REF.sub("", t)

    # 8. Standalone long digit sequences (document numbers without prefix)
    matches = _DOC_NUMBER.findall(t)
    if matches:
        report.doc_numbers_removed = len(matches)
        t = _DOC_NUMBER.sub("", t)

    # 9. Normalise whitespace
    t = _WHITESPACE.sub(" ", t).strip()

    return t, report


# ---------------------------------------------------------------------------
# Record-level sanitization (full scraped dict)
# ---------------------------------------------------------------------------

def sanitize_record(record: Dict[str, Any]) -> tuple[Dict[str, Any], PrivacyReport]:
    """
    Sanitize a full scraped record dict in-place (returns a new dict).

    Removes PII from:
      - record["text"]          — the post body
      - record["original_text"] — if present (must not store raw PII)
      - record["metadata"]      — strips keys listed in _PII_METADATA_KEYS

    The "url" field is kept because it is a public URL, not a personal identifier.
    The "platform" and "source" fields are aggregate identifiers, not personal data.

    Returns:
        (sanitized_record, PrivacyReport)
    """
    sanitized = dict(record)
    report = PrivacyReport()

    # Sanitize post text
    raw_text = sanitized.get("text") or ""
    clean, text_report = sanitize(raw_text)
    sanitized["text"] = clean

    # Merge text report counts
    report.mentions_removed      += text_report.mentions_removed
    report.profile_urls_removed  += text_report.profile_urls_removed
    report.emails_removed        += text_report.emails_removed
    report.phones_removed        += text_report.phones_removed
    report.cedulas_removed       += text_report.cedulas_removed
    report.doc_numbers_removed   += text_report.doc_numbers_removed
    report.contact_refs_removed  += text_report.contact_refs_removed

    # original_text must also be sanitized (or replaced) — we must not store raw PII
    # Use the sanitized text as original_text so downstream always sees clean content.
    if "original_text" in sanitized:
        sanitized["original_text"] = clean

    # Sanitize metadata dict
    metadata = sanitized.get("metadata") or {}
    if isinstance(metadata, dict):
        cleared: List[str] = []
        clean_metadata: Dict[str, Any] = {}
        for k, v in metadata.items():
            if k.lower() in _PII_METADATA_KEYS:
                cleared.append(k)
            else:
                clean_metadata[k] = v
        sanitized["metadata"] = clean_metadata
        report.metadata_keys_cleared = cleared

    return sanitized, report

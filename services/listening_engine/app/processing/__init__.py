"""
Processing layer — NLP pipeline for social sentiment monitoring.

Public API:
    process_record(record)   → ProcessedRecord   (single item, all 5 stages)
    run_pipeline(items)      → List[dict]         (batch, backward-compatible)
    clean_text(text)         → str
    detect_language(text)    → str
    classify_topic(text)     → (TopicLabel, float)
    classify_sentiment(text) → dict
    classify_urgency(text)   → (UrgencyLabel, float)
    sanitize(text)           → (str, PrivacyReport)   — Ley 1581 PII removal
    sanitize_record(record)  → (dict, PrivacyReport)  — full record PII removal
"""
from app.processing.pipeline import process_record, run_pipeline
from app.processing.normalizer import clean_text, normalize_text
from app.processing.language import detect_language
from app.processing.topics import classify_topic, extract_topics
from app.processing.sentiment import classify_sentiment
from app.processing.urgency import classify_urgency
from app.processing.privacy import sanitize, sanitize_record, PrivacyReport
from app.processing.schemas import ProcessedRecord, TopicLabel, SentimentLabel, UrgencyLabel

__all__ = [
    "process_record",
    "run_pipeline",
    "clean_text",
    "normalize_text",
    "detect_language",
    "classify_topic",
    "extract_topics",
    "classify_sentiment",
    "classify_urgency",
    "sanitize",
    "sanitize_record",
    "PrivacyReport",
    "ProcessedRecord",
    "TopicLabel",
    "SentimentLabel",
    "UrgencyLabel",
]

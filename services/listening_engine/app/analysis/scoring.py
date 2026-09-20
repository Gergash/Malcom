"""
Social Thermometer Score Algorithm.

Generates a weekly score (0-100) from:
  - number of mentions per topic
  - sentiment (positive reduces crisis, negative increases it)
  - urgency level (high urgency amplifies impact)
  - engagement (high engagement amplifies reach)

Configurable via config/scoring.yaml.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Default config path (relative to project root)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "scoring.yaml"


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load YAML scoring config."""
    p = path or DEFAULT_CONFIG_PATH
    if not p.exists():
        return _default_config()
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or _default_config()


def _default_config() -> Dict[str, Any]:
    return {
        "score": {"min": 0, "max": 100, "base": 100},
        "sentiment": {"positive": -0.5, "neutral": 0.0, "negative": 1.5},
        "urgency": {"low": 0.5, "medium": 1.0, "high": 2.0, "critical": 3.0},
        "engagement": {"enabled": True, "multiplier_cap": 2.0, "tiers": []},
        "topics": {},
        "trend": {"threshold_improving": 5, "threshold_declining": -5},
        "top_concerns_count": 5,
    }


def _engagement_multiplier(engagement: float, config: Dict[str, Any]) -> float:
    """Compute engagement multiplier from raw engagement count."""
    eng = config.get("engagement", {})
    if not eng.get("enabled", False):
        return 1.0
    cap = eng.get("multiplier_cap", 2.0)
    tiers = eng.get("tiers", [])
    mult = 1.0
    for t in sorted(tiers, key=lambda x: x.get("min_engagement", 0), reverse=True):
        if engagement >= t.get("min_engagement", 0):
            mult = t.get("multiplier", 1.0)
            break
    return min(mult, cap)


def _topic_weight(topic: str, config: Dict[str, Any]) -> float:
    return config.get("topics", {}).get(topic, 1.0)


def _sentiment_weight(sentiment_label: str, config: Dict[str, Any]) -> float:
    s = (sentiment_label or "neutral").lower()
    return config.get("sentiment", {}).get(s, config.get("sentiment", {}).get("neutral", 0.0))


def _urgency_multiplier(urgency: str, config: Dict[str, Any]) -> float:
    u = (urgency or "medium").lower()
    return config.get("urgency", {}).get(u, 1.0)


def compute_social_thermometer_score(
    mentions_per_topic: Dict[str, Dict[str, Any]],
    *,
    previous_week_score: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute weekly Social Thermometer Score (0-100).

    Args:
        mentions_per_topic: Nested structure per topic, e.g.:
            {
                "security": {
                    "count": 50,
                    "sentiment_distribution": {"positive": 10, "neutral": 20, "negative": 20},
                    "urgency_distribution": {"low": 5, "medium": 30, "high": 15},
                    "total_engagement": 500,
                },
                "taxes": { ... },
            }
        previous_week_score: Last week's score for trend.
        config: Override config (otherwise loaded from YAML).

    Returns:
        {
            "score": 62,
            "trend": "improving",
            "top_concerns": ["security", "taxes"],
            "raw_crisis_points": 38,
        }
    """
    cfg = config or load_config()
    score_cfg = cfg.get("score", {})
    base = score_cfg.get("base", 100)
    lo = score_cfg.get("min", 0)
    hi = score_cfg.get("max", 100)

    # Aggregate crisis points per topic
    topic_crisis: Dict[str, float] = {}
    for topic, data in mentions_per_topic.items():
        count = data.get("count", 0) or 0
        if count == 0:
            continue

        sent_dist = data.get("sentiment_distribution", {}) or data.get("sentiment", {})
        urg_dist = data.get("urgency_distribution", {}) or data.get("urgency", {})
        engagement = data.get("total_engagement", 0) or data.get("engagement", 0) or 0

        # Weighted average sentiment contribution (negative = crisis)
        sent_sum = sum(sent_dist.values()) or 1
        sent_contrib = 0.0
        for label, n in sent_dist.items():
            w = _sentiment_weight(label, cfg)
            sent_contrib += (n / sent_sum) * w

        # Weighted average urgency
        urg_sum = sum(urg_dist.values()) or 1
        urg_mult = 0.0
        for u, n in urg_dist.items():
            urg_mult += (n / urg_sum) * _urgency_multiplier(u, cfg)

        # Engagement amplification
        eng_mult = _engagement_multiplier(engagement / max(1, count), cfg)

        # Crisis = mentions * (sentiment effect) * urgency * engagement * topic_weight
        # Positive sentiment_contrib is negative, so it reduces crisis
        crisis = count * max(0, sent_contrib) * max(0.5, urg_mult) * eng_mult * _topic_weight(topic, cfg)
        topic_crisis[topic] = crisis

    total_crisis = sum(topic_crisis.values())
    raw_score = base - total_crisis
    score = max(lo, min(hi, round(raw_score, 1)))

    # Trend
    trend = "stable"
    if previous_week_score is not None:
        delta = score - previous_week_score
        th_imp = cfg.get("trend", {}).get("threshold_improving", 5)
        th_dec = cfg.get("trend", {}).get("threshold_declining", -5)
        if delta >= th_imp:
            trend = "improving"
        elif delta <= th_dec:
            trend = "declining"

    # Top concerns (highest crisis contribution)
    n_concerns = cfg.get("top_concerns_count", 5)
    sorted_topics = sorted(topic_crisis.items(), key=lambda x: -x[1])
    top_concerns = [t for t, _ in sorted_topics[:n_concerns] if topic_crisis.get(t, 0) > 0]

    return {
        "score": score,
        "trend": trend,
        "top_concerns": top_concerns,
        "raw_crisis_points": round(total_crisis, 2),
    }


def aggregate_weekly_data(
    posts: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate raw post data into mentions_per_topic structure for scoring.

    Each post should have:
      - topic (str) or topics (list)
      - sentiment_label or cached_sentiment_label
      - urgency or cached_urgency
      - engagement (optional) or metadata.engagement
    """
    acc: Dict[str, Dict[str, Any]] = {}

    for p in posts:
        topics = p.get("topics") or []
        if isinstance(p.get("topic"), str):
            topics = [p["topic"]]
        elif not topics:
            topics = [p.get("topic", "other")]
        if not topics:
            topics = ["other"]

        sent = (p.get("cached_sentiment_label") or p.get("sentiment_label") or "neutral").lower()
        urg = (p.get("cached_urgency") or p.get("urgency") or "medium").lower()
        eng = p.get("engagement") or (p.get("metadata") or {}).get("engagement", 0) or 0
        try:
            eng = int(eng)
        except (TypeError, ValueError):
            eng = 0

        for topic in topics:
            t = str(topic).lower().strip() or "other"
            if t not in acc:
                acc[t] = {
                    "count": 0,
                    "sentiment_distribution": {"positive": 0, "neutral": 0, "negative": 0},
                    "urgency_distribution": {"low": 0, "medium": 0, "high": 0, "critical": 0},
                    "total_engagement": 0,
                }
            acc[t]["count"] += 1
            acc[t]["sentiment_distribution"][sent] = acc[t]["sentiment_distribution"].get(sent, 0) + 1
            acc[t]["urgency_distribution"][urg] = acc[t]["urgency_distribution"].get(urg, 0) + 1
            acc[t]["total_engagement"] += eng

    return acc

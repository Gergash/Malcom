"""
Aggregation queries for the analytics API.
All public functions receive an AsyncSession and a filters object,
execute optimised SQLAlchemy queries and return plain dicts ready to be
serialised by the route layer.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.analysis_results import AnalysisResult, analysis_result_topics
from app.storage.models.posts import Post
from app.storage.models.sentiment_scores import SentimentScore
from app.storage.models.sources import Source
from app.storage.models.topics import Topic


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score(positive: int, negative: int, total: int) -> float:
    """Net sentiment score in [-1, 1]."""
    if not total:
        return 0.0
    return round((positive - negative) / total, 4)


def _pct(part: int, total: int) -> float:
    if not total:
        return 0.0
    return round(part / total * 100, 2)


def _apply_post_filters(q, filters):
    """Apply date-range and platform filters to a query that includes Post."""
    if filters.from_date:
        q = q.where(Post.posted_at >= filters.from_date)
    if filters.to_date:
        q = q.where(Post.posted_at <= filters.to_date)
    if filters.platform:
        q = q.where(Post.platform == filters.platform)
    return q


def _topic_post_ids(topic_slug: str):
    """Scalar subquery: post_ids classified under topic_slug."""
    return (
        select(AnalysisResult.post_id)
        .join(
            analysis_result_topics,
            analysis_result_topics.c.analysis_result_id == AnalysisResult.id,
        )
        .join(Topic, Topic.id == analysis_result_topics.c.topic_id)
        .where(Topic.slug == topic_slug)
        .where(AnalysisResult.post_id.isnot(None))
        .scalar_subquery()
    )


def _sentiment_cols():
    return (
        func.sum(case((Post.cached_sentiment_label == "positive", 1), else_=0)).label("positive"),
        func.sum(case((Post.cached_sentiment_label == "negative", 1), else_=0)).label("negative"),
        func.sum(case((Post.cached_sentiment_label == "neutral",  1), else_=0)).label("neutral"),
        func.count(Post.id).label("total"),
    )


def _breakdown(pos: int, neg: int, neu: int, tot: int) -> Dict[str, Any]:
    return {
        "positive": pos, "negative": neg, "neutral": neu, "total": tot,
        "score":        _score(pos, neg, tot),
        "positive_pct": _pct(pos, tot),
        "negative_pct": _pct(neg, tot),
        "neutral_pct":  _pct(neu, tot),
    }


# ---------------------------------------------------------------------------
# 1. Sentiment summary
# ---------------------------------------------------------------------------

async def get_sentiment_summary(db: AsyncSession, filters) -> Dict[str, Any]:
    """Overall + per-platform sentiment breakdown using cached_sentiment_label."""
    pos_col, neg_col, neu_col, tot_col = _sentiment_cols()

    q = select(pos_col, neg_col, neu_col, tot_col).where(
        Post.cached_sentiment_label.isnot(None)
    )
    q = _apply_post_filters(q, filters)
    if filters.topic:
        q = q.where(Post.id.in_(_topic_post_ids(filters.topic)))
    row = (await db.execute(q)).one()
    summary = _breakdown(
        int(row.positive or 0), int(row.negative or 0),
        int(row.neutral  or 0), int(row.total    or 0),
    )

    q_plat = (
        select(Post.platform, pos_col, neg_col, neu_col, tot_col)
        .where(Post.cached_sentiment_label.isnot(None))
        .group_by(Post.platform)
    )
    q_plat = _apply_post_filters(q_plat, filters)
    if filters.topic:
        q_plat = q_plat.where(Post.id.in_(_topic_post_ids(filters.topic)))

    by_platform: Dict[str, Any] = {}
    for r in (await db.execute(q_plat)).all():
        by_platform[r.platform] = _breakdown(
            int(r.positive or 0), int(r.negative or 0),
            int(r.neutral  or 0), int(r.total    or 0),
        )
    return {"summary": summary, "by_platform": by_platform}


# ---------------------------------------------------------------------------
# 2. Trending topics
# ---------------------------------------------------------------------------

async def get_trending_topics(
    db: AsyncSession,
    filters,
    limit: int = 10,
) -> Dict[str, Any]:
    """Most discussed topics with sentiment and urgency breakdown."""
    cnt_col  = func.count(AnalysisResult.id).label("count")
    pos_col  = func.sum(case((SentimentScore.label == "positive", 1), else_=0)).label("positive")
    neg_col  = func.sum(case((SentimentScore.label == "negative", 1), else_=0)).label("negative")
    neu_col  = func.sum(case((SentimentScore.label == "neutral",  1), else_=0)).label("neutral")
    high_col = func.sum(case((AnalysisResult.urgency == "high",   1), else_=0)).label("urgency_high")

    q = (
        select(Topic.slug, Topic.name, cnt_col, pos_col, neg_col, neu_col, high_col)
        .join(analysis_result_topics, analysis_result_topics.c.topic_id == Topic.id)
        .join(
            AnalysisResult,
            AnalysisResult.id == analysis_result_topics.c.analysis_result_id,
        )
        .outerjoin(SentimentScore, SentimentScore.id == AnalysisResult.sentiment_score_id)
        .join(Post, Post.id == AnalysisResult.post_id)
        .where(AnalysisResult.post_id.isnot(None))
        .group_by(Topic.id, Topic.slug, Topic.name)
        .order_by(cnt_col.desc())
        .limit(limit)
    )
    q = _apply_post_filters(q, filters)
    rows = (await db.execute(q)).all()

    total_q = (
        select(func.count(AnalysisResult.id))
        .join(Post, Post.id == AnalysisResult.post_id)
        .where(AnalysisResult.post_id.isnot(None))
    )
    total_q = _apply_post_filters(total_q, filters)
    total_classified: int = (await db.execute(total_q)).scalar() or 0

    topics = []
    for r in rows:
        cnt = int(r.count or 0)
        topics.append({
            "slug": r.slug, "name": r.name, "count": cnt,
            "positive": int(r.positive or 0), "neutral": int(r.neutral or 0),
            "negative": int(r.negative or 0), "urgency_high": int(r.urgency_high or 0),
            "share_pct": _pct(cnt, total_classified),
        })
    return {"topics": topics, "total_classified": total_classified}


# ---------------------------------------------------------------------------
# 3. Alerts
# ---------------------------------------------------------------------------

async def get_alerts(
    db: AsyncSession,
    filters,
    urgency_levels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """High-urgency negative posts, paginated. Uses cached_* fields."""
    if urgency_levels is None:
        urgency_levels = ["high"]

    base = (
        select(Post, Source.name.label("source_name"))
        .outerjoin(Source, Source.id == Post.source_id)
        .where(Post.cached_urgency.in_(urgency_levels))
        .where(Post.cached_sentiment_label == "negative")
    )
    base = _apply_post_filters(base, filters)
    if filters.topic:
        base = base.where(Post.id.in_(_topic_post_ids(filters.topic)))

    total: int = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    rows = (
        await db.execute(
            base.order_by(Post.posted_at.desc())
            .limit(filters.page_size)
            .offset(filters.offset)
        )
    ).all()

    items = []
    for row in rows:
        p: Post = row[0]
        items.append({
            "id":          p.id,
            "text":        (p.text or "")[:400],
            "platform":    p.platform,
            "source_name": row.source_name,
            "url":         p.url,
            "posted_at":   p.posted_at,
            "urgency":     p.cached_urgency,
            "sentiment":   p.cached_sentiment_label,
            "confidence":  float(p.cached_confidence) if p.cached_confidence is not None else None,
            "topic":       None,
        })
    return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# 4. Timeline
# ---------------------------------------------------------------------------

async def get_timeline(db: AsyncSession, filters) -> List[Dict[str, Any]]:
    """Daily sentiment counts + net score for trend charts."""
    day_col = func.date(Post.posted_at).label("date")
    pos_col = func.sum(case((Post.cached_sentiment_label == "positive", 1), else_=0)).label("positive")
    neg_col = func.sum(case((Post.cached_sentiment_label == "negative", 1), else_=0)).label("negative")
    neu_col = func.sum(case((Post.cached_sentiment_label == "neutral",  1), else_=0)).label("neutral")
    tot_col = func.count(Post.id).label("total")
    avg_col = func.avg(Post.cached_confidence).label("avg_confidence")

    q = (
        select(day_col, pos_col, neg_col, neu_col, tot_col, avg_col)
        .where(Post.cached_sentiment_label.isnot(None))
        .where(Post.posted_at.isnot(None))
        .group_by(func.date(Post.posted_at))
        .order_by(func.date(Post.posted_at))
    )
    q = _apply_post_filters(q, filters)
    if filters.topic:
        q = q.where(Post.id.in_(_topic_post_ids(filters.topic)))

    rows = (await db.execute(q)).all()
    points = []
    for r in rows:
        pos, neg, neu, tot = int(r.positive or 0), int(r.negative or 0), int(r.neutral or 0), int(r.total or 0)
        avg_conf = float(r.avg_confidence) if r.avg_confidence is not None else None
        points.append({
            "date": str(r.date), "positive": pos, "neutral": neu, "negative": neg,
            "total": tot, "score": _score(pos, neg, tot),
            "avg_confidence": round(avg_conf, 4) if avg_conf is not None else None,
        })
    return points


# ---------------------------------------------------------------------------
# 5. Source engagement
# ---------------------------------------------------------------------------

async def get_source_engagement(db: AsyncSession, filters) -> Dict[str, Any]:
    """Per-source engagement with sentiment, urgency and net score. Paginated."""
    pos_col  = func.sum(case((Post.cached_sentiment_label == "positive", 1), else_=0)).label("positive")
    neg_col  = func.sum(case((Post.cached_sentiment_label == "negative", 1), else_=0)).label("negative")
    neu_col  = func.sum(case((Post.cached_sentiment_label == "neutral",  1), else_=0)).label("neutral")
    high_col = func.sum(case((Post.cached_urgency == "high", 1), else_=0)).label("high_urgency")
    cnt_col  = func.count(Post.id).label("post_count")
    avg_col  = func.avg(Post.cached_confidence).label("avg_confidence")
    last_col = func.max(Post.scraped_at).label("last_scraped_at")

    q_base = (
        select(
            Source.id.label("source_id"), Source.name, Source.platform,
            cnt_col, pos_col, neg_col, neu_col, high_col, avg_col, last_col,
        )
        .join(Post, Post.source_id == Source.id)
        .where(Source.is_active.is_(True))
        .group_by(Source.id, Source.name, Source.platform)
        .order_by(cnt_col.desc())
    )
    q_base = _apply_post_filters(q_base, filters)
    if filters.topic:
        q_base = q_base.where(Post.id.in_(_topic_post_ids(filters.topic)))

    total: int = (
        await db.execute(select(func.count()).select_from(q_base.subquery()))
    ).scalar() or 0

    rows = (await db.execute(q_base.limit(filters.page_size).offset(filters.offset))).all()
    items = []
    for r in rows:
        p, n, u, t = int(r.positive or 0), int(r.negative or 0), int(r.neutral or 0), int(r.post_count or 0)
        avg_conf = float(r.avg_confidence) if r.avg_confidence is not None else None
        items.append({
            "source_id": r.source_id, "name": r.name, "platform": r.platform,
            "post_count": t, "positive": p, "neutral": u, "negative": n,
            "high_urgency": int(r.high_urgency or 0),
            "avg_confidence": round(avg_conf, 4) if avg_conf is not None else None,
            "score": _score(p, n, t),
            "last_scraped_at": r.last_scraped_at,
        })
    return {"items": items, "total": total}

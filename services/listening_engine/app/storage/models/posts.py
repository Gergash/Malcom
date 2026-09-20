"""Posts table: scraped posts/tweets/articles with optional denormalized analytics cache."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.storage.database import Base


class Post(Base):
    """
    Single scraped post (Facebook post, tweet, news article).
    Stores source, platform, text, date. Optional cached sentiment/urgency/confidence
    from latest analysis for fast dashboard queries.
    """
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True)
    platform = Column(String(32), nullable=False, index=True)
    text = Column(Text, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    url = Column(String(2048), nullable=False)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", JSONB, default=dict, nullable=False)
    language = Column(String(8), nullable=True)  # ISO 639-1, e.g. 'es'

    # Denormalized cache from latest analysis for fast analytics
    cached_sentiment_label = Column(String(64), nullable=True, index=True)
    cached_sentiment_score = Column(Numeric(5, 4), nullable=True)
    cached_urgency = Column(String(32), nullable=True, index=True)
    cached_confidence = Column(Numeric(5, 4), nullable=True)

    source = relationship("Source", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    analysis_results = relationship("AnalysisResult", back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_posts_platform_posted_at", "platform", "posted_at"),
        Index("ix_posts_scraped_at", "scraped_at"),
        Index("ix_posts_sentiment_platform", "cached_sentiment_label", "platform"),
        Index("ix_posts_posted_at_desc", "posted_at", postgresql_using="btree", postgresql_ops={"posted_at": "DESC"}),
    )

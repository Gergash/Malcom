"""Analysis_results table and M2M with topics: NLP output per post/comment."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.storage.database import Base


# Many-to-many: analysis_result <-> topics
analysis_result_topics = Table(
    "analysis_result_topics",
    Base.metadata,
    Column("analysis_result_id", Integer, ForeignKey("analysis_results.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", Integer, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_art_topic_id", "topic_id"),
    Index("ix_art_analysis_result_id", "analysis_result_id"),
)


class AnalysisResult(Base):
    """
    One NLP analysis result for a post or comment.
    Stores sentiment (FK to sentiment_scores), urgency, confidence, and links to topics via M2M.
    """
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    sentiment_score_id = Column(Integer, ForeignKey("sentiment_scores.id", ondelete="SET NULL"), nullable=True, index=True)
    urgency = Column(String(32), nullable=True, index=True)  # low, medium, high, critical
    confidence = Column(Numeric(5, 4), nullable=True)  # 0.0000 - 1.0000
    model_version = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    post = relationship("Post", back_populates="analysis_results")
    comment = relationship("Comment", back_populates="analysis_results")
    sentiment_score = relationship("SentimentScore", back_populates="analysis_results")
    topics = relationship("Topic", secondary=analysis_result_topics, backref="analysis_results")

    __table_args__ = (
        Index("ix_analysis_results_post_created", "post_id", "created_at"),
        Index("ix_analysis_results_comment_created", "comment_id", "created_at"),
        Index("ix_analysis_results_sentiment", "sentiment_score_id"),
        # `urgency` already gets `ix_analysis_results_urgency` from `index=True` above —
        # an extra explicit Index() with the same name collides on create_all().
        Index("ix_analysis_results_created_at", "created_at"),
    )

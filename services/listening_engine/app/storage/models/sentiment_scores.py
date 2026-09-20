"""Sentiment_scores table: dimension/lookup for sentiment labels and numeric scores."""
from sqlalchemy import Column, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.storage.database import Base


class SentimentScore(Base):
    """
    Lookup table for sentiment: label (positive/negative/neutral) and numeric score.
    analysis_results references this for consistent filtering and aggregations.
    """
    __tablename__ = "sentiment_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(64), nullable=False, unique=True, index=True)
    score_value = Column(Numeric(5, 4), nullable=False)  # e.g. -1.0, 0.0, 1.0
    description = Column(Text, nullable=True)

    analysis_results = relationship("AnalysisResult", back_populates="sentiment_score")

    # `label` already gets `ix_sentiment_scores_label` from `unique=True, index=True`
    # above — no additional `__table_args__` index needed (same name would collide
    # on create_all()).

"""Comments table: comments on posts."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.storage.database import Base


class Comment(Base):
    """Comment on a post (e.g. Facebook comment, tweet reply)."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    author_identifier = Column(String(255), nullable=True, index=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", JSONB, default=dict, nullable=False)

    post = relationship("Post", back_populates="comments")
    analysis_results = relationship("AnalysisResult", back_populates="comment", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_comments_post_posted", "post_id", "posted_at"),
    )

"""Sources table: registered social/news sources for ingestion."""
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.storage.database import Base


class Source(Base):
    """
    Registered source (Facebook page, Instagram profile, news site, etc.).
    Used to drive scraping jobs and to join with posts for analytics.
    """
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    platform = Column(String(32), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    posts = relationship("Post", back_populates="source", lazy="selectin")

    __table_args__ = (
        Index("ix_sources_platform_active", "platform", "is_active"),
    )

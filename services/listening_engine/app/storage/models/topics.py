"""Topics table: taxonomy for classification (culture, education, security, etc.)."""
from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.storage.database import Base


class Topic(Base):
    """
    Topic category for analysis (e.g. cultura, educación, seguridad).
    Optional hierarchy via parent_id for sub-topics.
    """
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    parent_id = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)

    parent = relationship("Topic", remote_side="Topic.id", backref="children")

    __table_args__ = (
        # `slug` already gets `ix_topics_slug` from `unique=True, index=True` above —
        # an extra explicit Index() with the same name collides on create_all().
        Index("ix_topics_parent", "parent_id"),
    )

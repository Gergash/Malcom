"""Initial schema: sources, posts, comments, topics, sentiment_scores, analysis_results.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00

Stores: source, platform, text, date, topic, sentiment, urgency, confidence.
Indexes optimized for analytics (time-series, filters by platform/sentiment/topic).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # sources
    # -------------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_name", "sources", ["name"])
    op.create_index("ix_sources_platform", "sources", ["platform"])
    op.create_index("ix_sources_platform_active", "sources", ["platform", "is_active"])

    # -------------------------------------------------------------------------
    # posts
    # -------------------------------------------------------------------------
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("cached_sentiment_label", sa.String(64), nullable=True),
        sa.Column("cached_sentiment_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("cached_urgency", sa.String(32), nullable=True),
        sa.Column("cached_confidence", sa.Numeric(5, 4), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_posts_source_id", "posts", ["source_id"])
    op.create_index("ix_posts_platform", "posts", ["platform"])
    op.create_index("ix_posts_posted_at", "posts", ["posted_at"])
    op.create_index("ix_posts_scraped_at", "posts", ["scraped_at"])
    op.create_index("ix_posts_cached_sentiment_label", "posts", ["cached_sentiment_label"])
    op.create_index("ix_posts_cached_urgency", "posts", ["cached_urgency"])
    op.create_index("ix_posts_platform_posted_at", "posts", ["platform", "posted_at"])
    op.create_index("ix_posts_sentiment_platform", "posts", ["cached_sentiment_label", "platform"])
    op.execute("CREATE INDEX ix_posts_posted_at_desc ON posts (posted_at DESC NULLS LAST)")

    # -------------------------------------------------------------------------
    # comments
    # -------------------------------------------------------------------------
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author_identifier", sa.String(255), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_index("ix_comments_author_identifier", "comments", ["author_identifier"])
    op.create_index("ix_comments_post_posted", "comments", ["post_id", "posted_at"])

    # -------------------------------------------------------------------------
    # topics
    # -------------------------------------------------------------------------
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_topics_slug", "topics", ["slug"])
    op.create_index("ix_topics_parent", "topics", ["parent_id"])

    # -------------------------------------------------------------------------
    # sentiment_scores (dimension table)
    # -------------------------------------------------------------------------
    op.create_table(
        "sentiment_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("score_value", sa.Numeric(5, 4), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label"),
    )
    op.create_index("ix_sentiment_scores_label", "sentiment_scores", ["label"])

    # Seed default sentiment labels
    op.execute(
        sa.text("""
        INSERT INTO sentiment_scores (label, score_value, description) VALUES
        ('positive', 1.0, 'Positive sentiment'),
        ('neutral', 0.0, 'Neutral sentiment'),
        ('negative', -1.0, 'Negative sentiment')
        """)
    )

    # -------------------------------------------------------------------------
    # analysis_results
    # -------------------------------------------------------------------------
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("sentiment_score_id", sa.Integer(), nullable=True),
        sa.Column("urgency", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sentiment_score_id"], ["sentiment_scores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_results_post_id", "analysis_results", ["post_id"])
    op.create_index("ix_analysis_results_comment_id", "analysis_results", ["comment_id"])
    op.create_index("ix_analysis_results_sentiment_score_id", "analysis_results", ["sentiment_score_id"])
    op.create_index("ix_analysis_results_urgency", "analysis_results", ["urgency"])
    op.create_index("ix_analysis_results_created_at", "analysis_results", ["created_at"])
    op.create_index("ix_analysis_results_post_created", "analysis_results", ["post_id", "created_at"])
    op.create_index("ix_analysis_results_comment_created", "analysis_results", ["comment_id", "created_at"])

    # -------------------------------------------------------------------------
    # analysis_result_topics (M2M)
    # -------------------------------------------------------------------------
    op.create_table(
        "analysis_result_topics",
        sa.Column("analysis_result_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("analysis_result_id", "topic_id"),
    )
    op.create_index("ix_art_topic_id", "analysis_result_topics", ["topic_id"])
    op.create_index("ix_art_analysis_result_id", "analysis_result_topics", ["analysis_result_id"])


def downgrade() -> None:
    op.drop_table("analysis_result_topics")
    op.drop_table("analysis_results")
    op.drop_table("sentiment_scores")
    op.drop_table("topics")
    op.drop_table("comments")
    op.drop_table("posts")
    op.drop_table("sources")

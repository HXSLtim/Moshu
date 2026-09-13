"""原文版本与持久派生任务，回填仅复制当前原文。

Revision ID: a8d2e4f6b901
Revises: f7a91b2c340d
"""
from alembic import op
import sqlalchemy as sa

from app.db.memory_backfill import backfill_current_chapter_revisions, current_chapter_snapshots

revision = "a8d2e4f6b901"
down_revision = "f7a91b2c340d"
branch_labels = None
depends_on = None


def upgrade():
    current_chapter_snapshots(op.get_bind())
    op.create_table(
        "chapter_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_lifecycle_id", sa.String(32), nullable=False),
        sa.Column("chapter_lifecycle_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chapter_lifecycle_id", "version", name="uq_chapter_revision_version"),
        sa.CheckConstraint("version > 0", name="ck_chapter_revision_version_positive"),
    )
    op.create_table(
        "derived_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id"), nullable=False),
        sa.Column("novel_lifecycle_id", sa.String(32), nullable=False),
        sa.Column("source_revision_id", sa.String(36), sa.ForeignKey("chapter_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False, server_default="chapter_digest"),
        sa.Column("recipe_version", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("novel_lifecycle_id", "source_revision_id", "kind", "recipe_version", name="uq_derived_job_recipe"),
        sa.CheckConstraint("state IN ('queued','running','succeeded','failed','cancelled','superseded')", name="ck_derived_job_state"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_derived_job_attempts"),
    )
    op.create_index("ix_derived_jobs_claim", "derived_jobs", ["state", "available_at", "lease_until"])
    op.create_table(
        "chapter_digests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id"), nullable=False),
        sa.Column("source_revision_id", sa.String(36), sa.ForeignKey("chapter_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipe_version", sa.String(100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("state_change_candidates", sa.JSON(), nullable=False),
        sa.Column("open_threads", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_revision_id", "recipe_version", name="uq_chapter_digest_recipe"),
        sa.CheckConstraint("status IN ('ready','stale')", name="ck_chapter_digest_status"),
    )
    for table, columns in (
        ("chapter_revisions", ["novel_id", "chapter_id"]),
        ("derived_jobs", ["novel_id", "source_revision_id"]),
        ("chapter_digests", ["novel_id", "chapter_id", "source_revision_id"]),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    backfill_current_chapter_revisions(op.get_bind())


def downgrade():
    """先停 worker 并导出历史与任务后，才可执行这项结构回退。"""
    op.drop_table("chapter_digests")
    op.drop_table("derived_jobs")
    op.drop_table("chapter_revisions")

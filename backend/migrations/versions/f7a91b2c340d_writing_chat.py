"""持久化小说创作对话。

Revision ID: f7a91b2c340d
Revises: e6dc8b549c6d
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a91b2c340d"
down_revision = "e6dc8b549c6d"
branch_labels = None
depends_on = None


def upgrade():
    """仅新增对话表，不改动已有小说正文。"""
    op.create_table(
        "writing_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text(), nullable=False),
        sa.Column("base_content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("novel_id", "request_id", name="uq_writing_turn_request"),
    )
    op.create_index("ix_writing_turns_novel_id", "writing_turns", ["novel_id"])


def downgrade():
    """回滚前应备份对话表；本操作删除对话记录。"""
    op.drop_index("ix_writing_turns_novel_id", table_name="writing_turns")
    op.drop_table("writing_turns")

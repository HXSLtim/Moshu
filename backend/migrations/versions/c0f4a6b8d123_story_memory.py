"""增加结构化剧情、稳定实体与作者状态审阅，不覆盖既有事实。

Revision ID: c0f4a6b8d123
Revises: b9e3f5a7c012
"""
from alembic import op
import sqlalchemy as sa
from app.db.story_bible_integrity import STORY_FACT_CHECKS, STORY_EVENT_CHECKS, preflight_story_bible

revision = "c0f4a6b8d123"
down_revision = "b9e3f5a7c012"
branch_labels = None
depends_on = None


def _identity():
    return [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("novel_id", sa.Integer, sa.ForeignKey("novels.id"), nullable=False),
            sa.Column("novel_lifecycle_id", sa.String(32), nullable=False)]


def upgrade():
    preflight_story_bible(op.get_bind())
    op.create_table("story_memory_heads", sa.Column("novel_id", sa.Integer, sa.ForeignKey("novels.id"), primary_key=True),
                    sa.Column("novel_lifecycle_id", sa.String(32), nullable=False), sa.Column("version", sa.Integer, nullable=False),
                    sa.CheckConstraint("version >= 0", name="ck_story_memory_version"))
    op.create_table("story_entities", *_identity(), sa.Column("name", sa.String(100), nullable=False),
                    sa.Column("description", sa.String(500), nullable=False, server_default=""),
                    sa.Column("kind", sa.String(20), nullable=False),
                    sa.CheckConstraint("kind IN ('character','item','location','organization')", name="ck_story_entity_kind"),
                    sa.CheckConstraint("length(trim(name)) > 0", name="ck_story_entity_name"))
    op.create_table("story_outline_nodes", *_identity(), sa.Column("parent_id", sa.String(36)),
                    sa.Column("kind", sa.String(20), nullable=False), sa.Column("plot_status", sa.String(20), nullable=False),
                    sa.Column("chapter_number", sa.Integer), sa.Column("title", sa.String(200), nullable=False),
                    sa.Column("conflict", sa.Text, nullable=False), sa.Column("outcome", sa.Text, nullable=False),
                    sa.Column("origin", sa.String(20), nullable=False), sa.Column("source_refs", sa.JSON, nullable=False),
                    sa.Column("source_status", sa.String(20), nullable=False),
                    sa.CheckConstraint("kind IN ('volume','chapter','scene')", name="ck_story_outline_kind"),
                    sa.CheckConstraint("plot_status IN ('planned','occurred')", name="ck_story_outline_plot_status"),
                    sa.CheckConstraint("origin IN ('author','ai')", name="ck_story_outline_origin"),
                    sa.CheckConstraint("source_status IN ('ready','needs_review')", name="ck_story_outline_source_status"),
                    sa.CheckConstraint("chapter_number IS NULL OR chapter_number > 0", name="ck_story_outline_chapter"),
                    sa.CheckConstraint("kind = 'volume' OR chapter_number IS NOT NULL", name="ck_story_outline_position"),
                    sa.CheckConstraint("length(trim(title)) > 0", name="ck_story_outline_title"))
    op.create_table("story_state_candidates", *_identity(), sa.Column("entity_id", sa.String(36), nullable=False),
                    sa.Column("attribute", sa.String(100), nullable=False), sa.Column("value", sa.Text, nullable=False),
                    sa.Column("value_entity_id", sa.String(36)), sa.Column("effective_chapter", sa.Integer, nullable=False),
                    sa.Column("source_refs", sa.JSON, nullable=False), sa.Column("source_status", sa.String(20), nullable=False),
                    sa.Column("status", sa.String(20), nullable=False), sa.Column("reason", sa.Text, nullable=False),
                    sa.Column("fact_id", sa.Integer),
                    sa.CheckConstraint("effective_chapter > 0", name="ck_story_candidate_chapter"),
                    sa.CheckConstraint("status IN ('pending','confirmed','rejected','revoked')", name="ck_story_candidate_status"),
                    sa.CheckConstraint("source_status IN ('ready','needs_review')", name="ck_story_candidate_source_status"),
                    sa.CheckConstraint("length(trim(attribute)) > 0 AND length(trim(value)) > 0", name="ck_story_candidate_value"),
                    sa.CheckConstraint("status NOT IN ('confirmed','revoked') OR fact_id IS NOT NULL", name="ck_story_candidate_fact"))
    op.create_table("story_memory_commands", *_identity(), sa.Column("request_id", sa.String(36), nullable=False),
                    sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("result", sa.JSON, nullable=False),
                    sa.UniqueConstraint("novel_lifecycle_id", "request_id", name="uq_story_memory_request"))
    for table in ("story_entities", "story_outline_nodes", "story_state_candidates", "story_memory_commands"):
        op.create_index(f"ix_{table}_novel_id", table, ["novel_id"])
    for column in (
        sa.Column("entity_id", sa.String(36)), sa.Column("value_entity_id", sa.String(36)),
        sa.Column("novel_lifecycle_id", sa.String(32)),
        sa.Column("origin", sa.String(20), nullable=False, server_default="author"),
        sa.Column("source_refs", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("source_status", sa.String(20), nullable=False, server_default="ready"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    ):
        op.add_column("story_facts", column)
    # 旧版事实只有整数 novel_id；迁移时绑定当时作品生命周期，避免删除重建后串入同 ID 新作品。
    op.execute(sa.text(
        "UPDATE story_facts SET novel_lifecycle_id = "
        "(SELECT rag_lifecycle_id FROM novels WHERE novels.id = story_facts.novel_id) "
        "WHERE story_facts.novel_lifecycle_id IS NULL"
    ))
    op.create_index("ix_story_facts_entity_id", "story_facts", ["entity_id"])
    for table, checks in (("story_facts", STORY_FACT_CHECKS), ("story_events", STORY_EVENT_CHECKS)):
        with op.batch_alter_table(table) as batch:
            for name, expression in checks.items():
                batch.create_check_constraint(name, expression)


def downgrade():
    for table, checks in (("story_facts", STORY_FACT_CHECKS), ("story_events", STORY_EVENT_CHECKS)):
        with op.batch_alter_table(table) as batch:
            for name in checks:
                batch.drop_constraint(name, type_="check")
    op.drop_index("ix_story_facts_entity_id", table_name="story_facts")
    with op.batch_alter_table("story_facts") as batch:
        for name in ("entity_id", "value_entity_id", "novel_lifecycle_id", "origin", "source_refs", "source_status", "version"):
            batch.drop_column(name)
    for table in ("story_memory_commands", "story_state_candidates", "story_outline_nodes", "story_entities", "story_memory_heads"):
        op.drop_table(table)

"""持久保存本轮参考简介清单，旧轮次不伪造来源。

Revision ID: b9e3f5a7c012
Revises: a8d2e4f6b901
"""
from alembic import op
import sqlalchemy as sa

revision = "b9e3f5a7c012"
down_revision = "a8d2e4f6b901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("writing_turns", sa.Column("context_manifest", sa.JSON(), nullable=True))


def downgrade():
    """回退保留原始对话；历史参考清单需事先单独导出。"""
    with op.batch_alter_table("writing_turns") as batch:
        batch.drop_column("context_manifest")

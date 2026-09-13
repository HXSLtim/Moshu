"""保存与删除同事务记录可恢复投影任务。"""
from alembic import op
import sqlalchemy as sa

revision = 'e2b6c8d0f345'
down_revision = 'd1a5b7c9e234'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('projection_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('novel_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('novel_lifecycle_id', sa.String(32), nullable=False),
        sa.Column('source_lifecycle_id', sa.String(32), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('lease_token', sa.String(36)),
        sa.Column('lease_until', sa.DateTime()),
        sa.Column('error', sa.String(300)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('kind', 'source_lifecycle_id', 'source_version', name='uq_projection_source'),
        sa.CheckConstraint("state IN ('queued','running','succeeded','failed','superseded')", name='ck_projection_state'))
    op.create_index('ix_projection_jobs_novel_id', 'projection_jobs', ['novel_id'])
    op.create_index('ix_projection_claim', 'projection_jobs', ['state', 'available_at', 'lease_until'])


def downgrade():
    op.drop_table('projection_jobs')

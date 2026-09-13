"""显式创作任务、候选与作者决定审计。

Revision ID: d1a5b7c9e234
Revises: c0f4a6b8d123
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a5b7c9e234'
down_revision = 'c0f4a6b8d123'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('writing_generation_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('novel_lifecycle_id', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('source_scope', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('execution', sa.JSON(), nullable=True),
        sa.Column('error', sa.String(300), nullable=True),
        sa.Column('error_code', sa.String(60), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('deadline_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('novel_lifecycle_id', 'request_id', name='uq_writing_job_request'))
    op.create_index('ix_writing_generation_jobs_novel_id', 'writing_generation_jobs', ['novel_id'])
    op.create_index('ix_writing_generation_jobs_status', 'writing_generation_jobs', ['status'])
    for name, type_ in [('novel_lifecycle_id', sa.String(32)), ('chapter_lifecycle_id', sa.String(32)),
                        ('base_version', sa.Integer()), ('result', sa.JSON()), ('proposal_id', sa.String(36)),
                        ('execution', sa.JSON())]:
        op.add_column('writing_turns', sa.Column(name, type_, nullable=True))
    op.create_table('writing_proposals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('novel_lifecycle_id', sa.String(32), nullable=False),
        sa.Column('turn_id', sa.Integer(), sa.ForeignKey('writing_turns.id', ondelete='CASCADE'), nullable=True, unique=True),
        sa.Column('execution_job_id', sa.String(36), sa.ForeignKey('writing_generation_jobs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('chapter_id', sa.Integer(), nullable=True),
        sa.Column('chapter_lifecycle_id', sa.String(32), nullable=True),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('base_content_hash', sa.String(64), nullable=False),
        sa.Column('operation', sa.String(20), nullable=False),
        sa.Column('target_chapter_number', sa.Integer(), nullable=True),
        sa.Column('selection_start', sa.Integer(), nullable=True),
        sa.Column('selection_end', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('context_manifest', sa.JSON(), nullable=True),
        sa.Column('execution', sa.JSON(), nullable=True),
        sa.Column('adopted_chapter_id', sa.Integer(), nullable=True),
        sa.Column('adopted_version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('decided_at', sa.DateTime(), nullable=True))
    op.create_index('ix_writing_proposals_execution_job_id', 'writing_proposals', ['execution_job_id'])
    op.create_index('ix_writing_proposals_novel_id', 'writing_proposals', ['novel_id'])
    op.create_table('writing_adoptions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('proposal_id', sa.String(36), sa.ForeignKey('writing_proposals.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('novel_lifecycle_id', sa.String(32), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('base_content_hash', sa.String(64), nullable=False),
        sa.Column('candidate_content_hash', sa.String(64), nullable=False),
        sa.Column('approved_content_hash', sa.String(64), nullable=True),
        sa.Column('chapter_snapshot', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('novel_lifecycle_id', 'request_id', name='uq_writing_adoption_request'))
    op.create_index('ix_writing_adoptions_novel_id', 'writing_adoptions', ['novel_id'])


def downgrade():
    op.drop_table('writing_adoptions')
    op.drop_table('writing_proposals')
    op.drop_table('writing_generation_jobs')
    with op.batch_alter_table('writing_turns') as batch:
        for name in ('execution', 'proposal_id', 'result', 'base_version', 'chapter_lifecycle_id', 'novel_lifecycle_id'):
            batch.drop_column(name)

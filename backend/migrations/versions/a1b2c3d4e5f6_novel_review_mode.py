"""novels 增加审核模式列(confirm/auto/none)

Revision ID: a1b2c3d4e5f6
Revises: e2b6c8d0f345
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'e2b6c8d0f345'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('novels', sa.Column('review_mode', sa.String(length=16),
                                     nullable=False, server_default='confirm'))


def downgrade() -> None:
    op.drop_column('novels', 'review_mode')

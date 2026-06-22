"""add daily closures and jira comment id

Revision ID: b38e71ac3209
Revises: aca9d22b4dbc
Create Date: 2026-06-22 15:50:01.341962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b38e71ac3209'
down_revision: Union[str, Sequence[str], None] = 'aca9d22b4dbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'daily_closures',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('report_date', sa.String(), nullable=False),
        sa.Column('finalized_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'report_date', name='uq_daily_closures_user_date'),
    )
    op.add_column('status_reports', sa.Column('jira_comment_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('status_reports', 'jira_comment_id')
    op.drop_table('daily_closures')

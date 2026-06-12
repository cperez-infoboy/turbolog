"""drop_jira_connections_table

Revision ID: 68c029c4286e
Revises: 073b113da761
Create Date: 2026-06-12 09:33:59.821379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68c029c4286e'
down_revision: Union[str, Sequence[str], None] = '073b113da761'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop jira_connections table — JIRA auth is now a global admin token."""
    op.drop_table("jira_connections")


def downgrade() -> None:
    """Recreate jira_connections table."""
    op.create_table(
        "jira_connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jira_email", sa.String(), nullable=False),
        sa.Column("jira_api_token_encrypted", sa.String(), nullable=False),
        sa.Column("jira_domain", sa.String(), nullable=False),
        sa.Column("last_verified", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )

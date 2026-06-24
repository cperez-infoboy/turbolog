"""add allowed_emails table

Revision ID: 4e9aadb4fe66
Revises: 40526f93ceed
Create Date: 2026-06-24 12:00:00.000000

Creates the ``allowed_emails`` access-control table with a unique index on
``email`` and backfills it from existing users so nobody is locked out on
deploy. Removal of a row revokes login access on the next attempt.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e9aadb4fe66'
down_revision: Union[str, Sequence[str], None] = '40526f93ceed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema + backfill existing users into the allow-list."""
    op.create_table(
        'allowed_emails',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('added_by', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['added_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_allowed_emails_email', 'allowed_emails', ['email'], unique=True
    )

    # Backfill: every distinct existing user email is authorized, so the deploy
    # does not lock anyone out and revocation works from day one. The id is a
    # stable md5 hex (32 chars) derived from the normalized email -- compatible
    # with the String(32) primary key shape.
    op.execute("""
        INSERT INTO allowed_emails (id, email, created_at)
        SELECT md5(t.e), t.e, now()::text
        FROM (
            SELECT DISTINCT lower(email) AS e
            FROM users
            WHERE email IS NOT NULL AND email <> ''
        ) t
    """)


def downgrade() -> None:
    """Downgrade schema. Dropping the table also removes the backfilled rows."""
    op.drop_index('ix_allowed_emails_email', table_name='allowed_emails')
    op.drop_table('allowed_emails')

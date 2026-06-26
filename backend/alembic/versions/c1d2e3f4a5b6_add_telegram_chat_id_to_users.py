"""add telegram_chat_id to users

Revision ID: c1d2e3f4a5b6
Revises: be2af9f21169
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "be2af9f21169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "telegram_chat_id")

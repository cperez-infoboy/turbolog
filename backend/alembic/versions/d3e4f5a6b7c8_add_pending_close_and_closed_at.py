"""add pending_close and closed_at to status_reports

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "d3e4f5a6b7c8"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "status_reports",
        sa.Column("pending_close", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "status_reports",
        sa.Column("closed_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("status_reports", "closed_at")
    op.drop_column("status_reports", "pending_close")

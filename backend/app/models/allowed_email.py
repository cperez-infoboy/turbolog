import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AllowedEmail(Base):
    """An email authorized to log in to Turbolog.

    The gate (``can_login``) accepts a Google-verified email if it is in the
    immutable ``ADMIN_EMAILS`` seed OR a row with that normalized (lowercase)
    email exists here. Removing a row revokes access on the next login.
    """

    __tablename__ = "allowed_emails"
    __table_args__ = (Index("ix_allowed_emails_email", "email", unique=True),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    added_by: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )

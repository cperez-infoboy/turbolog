import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DailyClosure(Base):
    """Records that a user has closed (finalized) the status reports for a date.

    Presence of a (user_id, report_date) row locks that day: status reports can
    no longer be created, edited, or deleted, because they have been posted to
    JIRA as comments.
    """

    __tablename__ = "daily_closures"
    __table_args__ = (
        UniqueConstraint("user_id", "report_date", name="uq_daily_closures_user_date"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    report_date: Mapped[str] = mapped_column(String, nullable=False)
    finalized_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    user = relationship("User", back_populates="daily_closures")

import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, false, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StatusReport(Base):
    __tablename__ = "status_reports"
    __table_args__ = (
        Index(
            "ix_status_reports_user_task_date",
            "user_id",
            "task_key",
            "report_date",
            unique=True,
        ),
        Index("ix_status_reports_user_date", "user_id", "report_date"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(String, nullable=False)
    report_date: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    jira_comment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_close: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: Mapped[str] = mapped_column(
        String,
        default=lambda: datetime.now(timezone.utc).isoformat(),
        onupdate=lambda: datetime.now(timezone.utc).isoformat(),
    )

    user = relationship("User", back_populates="status_reports")

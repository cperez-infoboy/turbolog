import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_jira_key", "user_id", "jira_key", unique=True),
        Index("ix_tasks_user_fetched_at", "user_id", "fetched_at"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    jira_key: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    status_category: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)
    project_key: Mapped[str | None] = mapped_column(String, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    user = relationship("User")

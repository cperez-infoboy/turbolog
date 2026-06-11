import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), unique=True, nullable=False
    )
    jira_email: Mapped[str] = mapped_column(String, nullable=False)
    jira_api_token_encrypted: Mapped[str] = mapped_column(
        String, nullable=False
    )
    jira_domain: Mapped[str] = mapped_column(String, nullable=False)
    last_verified: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    user = relationship("User", back_populates="jira_connection")

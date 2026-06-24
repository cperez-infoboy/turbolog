import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    google_sub: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    picture: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    is_audited: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    status_reports = relationship(
        "StatusReport", back_populates="user", lazy="selectin"
    )
    daily_closures = relationship(
        "DailyClosure", back_populates="user", lazy="selectin"
    )

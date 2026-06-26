import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditPeriod(Base):
    """Records a continuous stretch where a user was under audit.

    When an admin enables ``is_audited`` on a user, a new period opens
    (``ended_at=None``).  When they disable it, the period closes
    (``ended_at`` is set).  The audit service uses these periods to count
    only the days that were actually under audit, avoiding phantom faltas
    from before the system went live or from gaps when audit was disabled.
    """

    __tablename__ = "audit_periods"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    started_at: Mapped[str] = mapped_column(
        String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    user = relationship("User", back_populates="audit_periods")

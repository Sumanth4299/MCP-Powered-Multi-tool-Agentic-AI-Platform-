from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class ReminderStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    PROCESSING = "processing"  # Transient lock state to avoid duplicate dispatch
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Reminder(Base, TimestampMixin):
    """
    Durable persistent state for task reminders.
    Survives server reboots and powers the polling engine.
    """
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[ReminderStatus] = mapped_column(
        SAEnum(ReminderStatus, name="reminder_status", native_enum=False),
        default=ReminderStatus.SCHEDULED,
        nullable=False,
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_reminders_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_reminders_user_task", "user_id", "task_id"),
    )

    def __repr__(self) -> str:
        return f"<Reminder id={self.id} task_id={self.task_id} scheduled_at={self.scheduled_at} status={self.status}>"


class InAppNotification(Base, TimestampMixin):
    """
    Durable in-app notification inbox delivered to users upon reminder trigger.
    """
    __tablename__ = "in_app_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<InAppNotification id={self.id} user_id={self.user_id} title='{self.title[:20]}'>"
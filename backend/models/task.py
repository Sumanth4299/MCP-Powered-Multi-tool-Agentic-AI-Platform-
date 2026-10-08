from datetime import datetime
import enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Task(Base, TimestampMixin):
    """
    Core Task entity enforcing strict foreign-key tenant boundaries.
    
    Includes soft-delete tracking (`deleted_at`) and source provenance
    for tracking actions generated manually vs. autonomously via MCP tools.
    """
    __tablename__ = "tasks"

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
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="task_priority", native_enum=False),
        default=TaskPriority.MEDIUM,
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=False),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(50),
        default="manual",
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # Composite indices for high-frequency user-isolated queries
    __table_args__ = (
        Index("ix_tasks_user_status_deleted", "user_id", "status", "deleted_at"),
        Index("ix_tasks_user_due_at", "user_id", "due_at"),
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} user_id={self.user_id} title='{self.title[:20]}' status={self.status}>"
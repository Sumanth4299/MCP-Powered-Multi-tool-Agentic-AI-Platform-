from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.models.task import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Brief task summary")
    description: str | None = Field(default=None, description="Detailed context or markdown notes")
    due_at: datetime | None = Field(default=None, description="Timezone-aware deadline")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task urgency level")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Initial task workflow stage")
    source: str = Field(default="manual", max_length=50, description="Origin: manual, mcp_agent, slack, etc.")


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_at: datetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    source: str | None = Field(default=None, max_length=50)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    description: str | None
    due_at: datetime | None
    priority: TaskPriority
    status: TaskStatus
    source: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskFilterParams(BaseModel):
    status: TaskStatus | None = Field(default=None, description="Filter by status")
    priority: TaskPriority | None = Field(default=None, description="Filter by priority")
    search: str | None = Field(default=None, max_length=100, description="Case-insensitive search on title/desc")
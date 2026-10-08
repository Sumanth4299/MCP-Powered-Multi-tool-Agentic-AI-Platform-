"""
MCP Task Server: Exposes personal task management primitives to MCP agent clients.

Security Model:
- `user_id` is NEVER accepted as an LLM argument. It is extracted strictly from the
  underlying MCP server context headers/metadata set during connection handshake.
- Destructive actions enforce safety guardrails (confirmation flags).
- Reuses `TaskService` directly, maintaining uniform business logic with the REST API.
"""

from contextvars import ContextVar
from datetime import datetime
import json
from typing import Any
import uuid

# Resilient FastMCP imports satisfying Pylance type stubs
try:
    from mcp.server.fastmcp import FastMCP, Context  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    from fastmcp import FastMCP, Context  # type: ignore[no-redef]
from pydantic import BaseModel, Field, field_validator

from backend.database import async_session_factory
from backend.models.task import TaskPriority, TaskStatus
from backend.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from backend.services.task_service import TaskService

# Server instance
mcp = FastMCP(
    name="Personal Task Management Server",
    instructions=(
        "Manage the user's personal task list. Always use ISO 8601 formatting "
        "(e.g., '2026-10-15T14:30:00Z') for due dates. Destructive actions require "
        "explicit user confirmation."
    ),
)

# ContextVar fallback for stdio runner environments
current_user_id_ctx: ContextVar[uuid.UUID | None] = ContextVar("current_user_id_ctx", default=None)


def _resolve_authenticated_user_id(ctx: Context) -> uuid.UUID:
    """
    Extract the authenticated user_id securely from the MCP session context.
    Checks HTTP/SSE metadata headers first, then falls back to contextual execution scope.
    """
    # 1. Attempt resolution from FastMCP session metadata / HTTP request headers (SSE transport)
    if hasattr(ctx, "session") and ctx.session is not None:
        meta = getattr(ctx.session, "metadata", {}) or {}
        header_user_id = meta.get("user-id") or meta.get("x-user-id")
        if header_user_id:
            try:
                return uuid.UUID(str(header_user_id))
            except ValueError:
                pass

    # 2. Attempt resolution from execution context variable (stdio transport)
    bound_id = current_user_id_ctx.get()
    if bound_id:
        return bound_id

    raise PermissionError("Access Denied: Unauthenticated MCP tool execution context.")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Validate and parse ISO 8601 strings into timezone-aware datetimes."""
    if not value or not value.strip():
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as err:
        raise ValueError(
            f"Invalid datetime '{value}'. Must be ISO 8601 format (e.g., '2026-10-25T18:00:00Z')."
        ) from err


# --- Tool Argument Validation Schemas ---

class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Clear, actionable task summary.")
    description: str | None = Field(default=None, description="Optional Markdown notes, context, or links.")
    due_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp with timezone offset (e.g., '2026-10-31T23:59:59Z').",
    )
    priority: str = Field(
        default="medium",
        description="Task priority. Allowed values: 'low', 'medium', 'high'.",
    )

    @field_validator("priority")
    @classmethod
    def check_priority(cls, v: str) -> str:
        if v.lower() not in {"low", "medium", "high"}:
            raise ValueError("Priority must be one of: 'low', 'medium', 'high'.")
        return v.lower()


class UpdateTaskInput(BaseModel):
    task_id: str = Field(..., description="UUID string identifying the task to update.")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    due_at: str | None = Field(
        default=None,
        description="Updated ISO 8601 timestamp (e.g., '2026-11-05T09:00:00Z') or empty string to unset.",
    )
    priority: str | None = Field(
        default=None,
        description="Updated priority: 'low', 'medium', 'high'.",
    )


# --- Standardized MCP Tools ---

@mcp.tool(
    name="create_task",
    description="Create a new task for the authenticated user. Never accept user_id.",
)
async def create_task(
    title: str,
    description: str | None = None,
    due_at: str | None = None,
    priority: str = "medium",
    ctx: Any = None,
) -> str:
    """
    Args:
        title: Short title describing the task.
        description: Detailed notes or instructions.
        due_at: ISO 8601 datetime format (e.g. '2026-10-20T17:00:00Z').
        priority: Urgency indicator ('low', 'medium', 'high').
    """
    user_id = _resolve_authenticated_user_id(ctx)
    args = CreateTaskInput(title=title, description=description, due_at=due_at, priority=priority)
    parsed_due = _parse_iso_datetime(args.due_at)

    task_in = TaskCreate(
        title=args.title,
        description=args.description,
        due_at=parsed_due,
        priority=TaskPriority(args.priority),
        source="mcp_agent",
    )

    async with async_session_factory() as db:
        task = await TaskService.create_task(db=db, user_id=user_id, data=task_in)
        return json.dumps(TaskResponse.model_validate(task).model_dump(mode="json"), indent=2)


@mcp.tool(
    name="list_tasks",
    description="List active non-deleted tasks for the user with optional status and priority filters.",
)
async def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    ctx: Context = None,
) -> str:
    """
    Args:
        status: Filter tasks by state ('pending', 'in_progress', 'completed').
        priority: Filter tasks by urgency ('low', 'medium', 'high').
    """
    user_id = _resolve_authenticated_user_id(ctx)

    status_enum = TaskStatus(status.lower()) if status else None
    priority_enum = TaskPriority(priority.lower()) if priority else None

    async with async_session_factory() as db:
        tasks = await TaskService.list_tasks(
            db=db,
            user_id=user_id,
            status=status_enum,
            priority=priority_enum,
        )
        data = [TaskResponse.model_validate(t).model_dump(mode="json") for t in tasks]
        return json.dumps(data, indent=2)


@mcp.tool(
    name="get_task",
    description="Retrieve full details for a single task by its unique UUID.",
)
async def get_task(task_id: str, ctx: Context = None) -> str:
    """
    Args:
        task_id: Valid UUID string identifying the target task.
    """
    user_id = _resolve_authenticated_user_id(ctx)
    try:
        parsed_task_id = uuid.UUID(task_id.strip())
    except ValueError:
        return json.dumps({"error": f"Invalid UUID format: '{task_id}'"})

    async with async_session_factory() as db:
        task = await TaskService.get_task(db=db, user_id=user_id, task_id=parsed_task_id)
        if not task:
            return json.dumps({"error": f"Task '{task_id}' not found."})
        return json.dumps(TaskResponse.model_validate(task).model_dump(mode="json"), indent=2)


@mcp.tool(
    name="search_tasks",
    description="Perform full-text search across titles and descriptions of the user's tasks.",
)
async def search_tasks(query: str, ctx: Context = None) -> str:
    """
    Args:
        query: Keywords to search within task title and description fields.
    """
    user_id = _resolve_authenticated_user_id(ctx)
    sanitized = query.strip()
    if not sanitized:
        return json.dumps([])

    async with async_session_factory() as db:
        tasks = await TaskService.list_tasks(db=db, user_id=user_id, search=sanitized)
        data = [TaskResponse.model_validate(t).model_dump(mode="json") for t in tasks]
        return json.dumps(data, indent=2)


@mcp.tool(
    name="update_task",
    description="Update mutable fields (title, due_at, priority) of an existing task.",
)
async def update_task(
    task_id: str,
    title: str | None = None,
    due_at: str | None = None,
    priority: str | None = None,
    ctx: Context = None,
) -> str:
    """
    Args:
        task_id: UUID of the task to update.
        title: Optional replacement title.
        due_at: Optional replacement ISO 8601 timestamp.
        priority: Optional replacement priority ('low', 'medium', 'high').
    """
    user_id = _resolve_authenticated_user_id(ctx)
    args = UpdateTaskInput(task_id=task_id, title=title, due_at=due_at, priority=priority)

    try:
        parsed_id = uuid.UUID(args.task_id)
    except ValueError:
        return json.dumps({"error": f"Invalid task UUID: '{task_id}'"})

    parsed_due = _parse_iso_datetime(args.due_at) if args.due_at else None
    prio_enum = TaskPriority(args.priority.lower()) if args.priority else None

    patch = TaskUpdate(
        title=args.title,
        due_at=parsed_due,
        priority=prio_enum,
    )

    async with async_session_factory() as db:
        updated = await TaskService.update_task(
            db=db,
            user_id=user_id,
            task_id=parsed_id,
            data=patch,
        )
        if not updated:
            return json.dumps({"error": f"Task '{task_id}' not found."})
        return json.dumps(TaskResponse.model_validate(updated).model_dump(mode="json"), indent=2)


@mcp.tool(
    name="complete_task",
    description="Mark a task as completed and set the completion timestamp.",
)
async def complete_task(task_id: str, ctx: Context = None) -> str:
    """
    Args:
        task_id: UUID of the task to complete.
    """
    user_id = _resolve_authenticated_user_id(ctx)
    try:
        parsed_id = uuid.UUID(task_id.strip())
    except ValueError:
        return json.dumps({"error": f"Invalid UUID: '{task_id}'"})

    async with async_session_factory() as db:
        completed = await TaskService.complete_task(
            db=db,
            user_id=user_id,
            task_id=parsed_id,
        )
        if not completed:
            return json.dumps({"error": f"Task '{task_id}' not found."})
        return json.dumps(TaskResponse.model_validate(completed).model_dump(mode="json"), indent=2)


@mcp.tool(
    name="delete_task",
    description="Soft-delete a task. Requires explicit confirm=True safeguard flag.",
)
async def delete_task(
    task_id: str,
    confirm: bool = False,
    ctx: Context = None,
) -> str:
    """
    Args:
        task_id: UUID of the task to soft-delete.
        confirm: Safety switch. Must be explicitly True. If False, the operation is blocked.
    """
    if not confirm:
        return json.dumps({
            "status": "confirmation_required",
            "message": (
                f"Destructive action blocked: deleting task '{task_id}' requires explicit "
                "user confirmation. Ask the user for confirmation and re-run with confirm=True."
            ),
        })

    user_id = _resolve_authenticated_user_id(ctx)
    try:
        parsed_id = uuid.UUID(task_id.strip())
    except ValueError:
        return json.dumps({"error": f"Invalid UUID: '{task_id}'"})

    async with async_session_factory() as db:
        success = await TaskService.delete_task(
            db=db,
            user_id=user_id,
            task_id=parsed_id,
        )
        if not success:
            return json.dumps({"error": f"Task '{task_id}' not found."})
        return json.dumps({"status": "success", "message": f"Task {task_id} deleted."})


if __name__ == "__main__":
    # Standard entrypoint for stdio or SSE transport
    mcp.run()
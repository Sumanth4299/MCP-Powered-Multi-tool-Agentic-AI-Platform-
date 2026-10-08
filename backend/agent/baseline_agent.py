"""
Baseline Agent Implementation: Direct In-Process Function Calling.
Used for academic comparison against the MCP-based agent architecture.
"""

from datetime import datetime, timezone
import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.database import async_session_factory
from backend.models.task import TaskPriority, TaskStatus
from backend.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from backend.services.task_service import TaskService
from mcp_servers.calendar_server import check_calendar_availability, get_calendar_events
from mcp_servers.holiday_server import check_holidays

settings = get_settings()


# Hard-coded Pydantic schemas tightly coupled to the local agent loop
class DirectCreateTaskInput(BaseModel):
    title: str = Field(..., description="Title of the task")
    description: str | None = Field(default=None, description="Task notes")
    due_at: str | None = Field(default=None, description="ISO 8601 string")
    priority: str = Field(default="medium", description="low, medium, high")


class DirectSearchTaskInput(BaseModel):
    query: str = Field(..., description="Search keyword")


class DirectHolidayInput(BaseModel):
    date: str = Field(..., description="Target date YYYY-MM-DD")
    region: str = Field(default="India", description="Region")


class DirectAvailabilityInput(BaseModel):
    start_date: str = Field(..., description="ISO 8601 start timestamp")
    end_date: str = Field(..., description="ISO 8601 end timestamp")


def build_hardcoded_tools(user_id: uuid.UUID) -> list[StructuredTool]:
    """Manually builds and binds in-process Python functions."""

    async def _create(title: str, description: str | None = None, due_at: str | None = None, priority: str = "medium") -> str:
        parsed_due = datetime.fromisoformat(due_at.replace("Z", "+00:00")) if due_at else None
        async with async_session_factory() as db:
            task = await TaskService.create_task(
                db=db,
                user_id=user_id,
                data=TaskCreate(
                    title=title,
                    description=description,
                    due_at=parsed_due,
                    priority=TaskPriority(priority.lower()),
                ),
            )
            return json.dumps(TaskResponse.model_validate(task).model_dump(mode="json"))

    async def _search(query: str) -> str:
        async with async_session_factory() as db:
            tasks = await TaskService.list_tasks(db=db, user_id=user_id, search=query)
            return json.dumps([TaskResponse.model_validate(t).model_dump(mode="json") for t in tasks])

    async def _holidays(date: str, region: str = "India") -> str:
        return await check_holidays(date=date, region=region)

    async def _availability(start_date: str, end_date: str) -> str:
        return await check_calendar_availability(start_date=start_date, end_date=end_date)

    return [
        StructuredTool.from_function(
            coroutine=_create,
            name="create_task",
            description="Create task directly in db",
            args_schema=DirectCreateTaskInput,
        ),
        StructuredTool.from_function(
            coroutine=_search,
            name="search_tasks",
            description="Search tasks directly in db",
            args_schema=DirectSearchTaskInput,
        ),
        StructuredTool.from_function(
            coroutine=_holidays,
            name="check_holidays",
            description="Query local holiday list",
            args_schema=DirectHolidayInput,
        ),
        StructuredTool.from_function(
            coroutine=_availability,
            name="check_calendar_availability",
            description="Query Google calendar availability",
            args_schema=DirectAvailabilityInput,
        ),
    ]


async def run_baseline_agent(user_id: uuid.UUID, prompt: str, chat_history: list[Any] | None = None) -> dict[str, Any]:
    """Runs a single ReAct loop iteration using in-process hard-coded tools."""
    tools = build_hardcoded_tools(user_id)
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.0,
    ).bind_tools(tools)

    tools_by_name = {t.name: t for t in tools}
    messages = list(chat_history or [])
    messages.append(HumanMessage(content=prompt))

    tool_call_records = []
    response = await llm.ainvoke(messages)
    messages.append(response)

    if hasattr(response, "tool_calls") and response.tool_calls:
        for call in response.tool_calls:
            t_name = call["name"]
            t_args = call["args"]
            t_instance = tools_by_name.get(t_name)
            output = ""
            if t_instance:
                try:
                    output = await t_instance.ainvoke(t_args)
                except Exception as err:
                    output = f"Execution error: {str(err)}"
            tool_call_records.append({"tool": t_name, "args": t_args, "output": output})
            messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

        final_response = await llm.ainvoke(messages)
        final_text = final_response.content
    else:
        final_text = response.content

    return {
        "response": final_text,
        "tool_calls": tool_call_records,
    }

from datetime import datetime, timezone
import json
from typing import Any, Literal
import uuid
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph

from backend.agent.prompts import AGENT_SYSTEM_PROMPT
from backend.agent.state import AgentState, ToolExecutionRecord
from backend.agent.tools import get_federated_tools
from backend.config import get_settings


settings = get_settings()


def _current_datetime_instruction(now: datetime) -> str:
    local_now = now.astimezone(ZoneInfo("Asia/Kolkata"))
    current_time = local_now.strftime("%A, %Y-%m-%d %H:%M:%S")
    return (
        f"Current date and time: {current_time} "
        "(Asia/Kolkata, Hyderabad, Telangana)."
    )


def _build_system_prompt(now: datetime) -> str:
    return (
        f"{AGENT_SYSTEM_PROMPT}\n\n"
        f"{_current_datetime_instruction(now)}"
    )


def build_llm(tools: list[StructuredTool]) -> Any:
    """Initialize Gemini and bind the federated MCP tools."""
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.0,
    )
    return llm.bind_tools(tools)


async def agent_node(state: AgentState) -> dict[str, Any]:
    """LLM decision node using Gemini with federated MCP tools."""
    user_id = state["user_id"]

    tools = await get_federated_tools(user_id=user_id)
    llm = build_llm(tools)

    messages = list(state["messages"])
    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    if not messages or not isinstance(messages[0], SystemMessage):
        messages.insert(
            0,
            SystemMessage(content=_build_system_prompt(now)),
        )
    elif isinstance(messages[0].content, str):
        system_content = messages[0].content.split(
            "\n\nCurrent date and time:", maxsplit=1
        )[0]
        messages[0] = SystemMessage(
            content=(
                f"{system_content}\n\n"
                f"{_current_datetime_instruction(now)}"
            )
        )
    else:
        messages.insert(
            1,
            SystemMessage(content=_current_datetime_instruction(now)),
        )

    response = await llm.ainvoke(messages)

    return {"messages": [response]}


async def guardrails_and_tools_node(
    state: AgentState,
) -> dict[str, Any]:
    """
    Execute Gemini tool calls with safety interception.
    Record tool execution telemetry in tool_call_history.
    """
    user_id = state["user_id"]
    last_message = state["messages"][-1]

    tool_messages: list[ToolMessage] = []
    execution_records: list[ToolExecutionRecord] = []

    tools_by_name = {
        tool.name: tool
        for tool in await get_federated_tools(user_id=user_id)
    }

    # Safely extract tool calls from the last message.
    tool_calls = getattr(last_message, "tool_calls", None) or []

    if not isinstance(tool_calls, list):
        tool_calls = []

    for call in tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        call_id = call["id"]

        # Require explicit confirmation before deleting a task.
        if (
            tool_name == "delete_task"
            and not tool_args.get("confirm", False)
        ):
            output_str = (
                "Action Blocked: Deleting a task requires explicit user "
                "confirmation. Ask the user for confirmation before "
                "calling delete_task with confirm=True."
            )

            tool_messages.append(
                ToolMessage(
                    content=output_str,
                    tool_call_id=call_id,
                )
            )

            execution_records.append(
                {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "output": output_str,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            continue

        tool_instance = tools_by_name.get(tool_name)

        if tool_instance is None:
            output_str = f"Tool '{tool_name}' is not registered."

            tool_messages.append(
                ToolMessage(
                    content=output_str,
                    tool_call_id=call_id,
                )
            )
            continue

        try:
            result = await tool_instance.ainvoke(tool_args)

            output_str = (
                result
                if isinstance(result, str)
                else json.dumps(result, default=str)
            )

        except Exception as exc:
            output_str = f"Tool execution failed: {str(exc)}"

        tool_messages.append(
            ToolMessage(
                content=output_str,
                tool_call_id=call_id,
            )
        )

        execution_records.append(
            {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "output": output_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    return {
        "messages": tool_messages,
        "tool_call_history": (
            state.get("tool_call_history", []) + execution_records
        ),
    }


def should_continue(
    state: AgentState,
) -> Literal["tools", "__end__"]:
    """Route to tools only when a valid list of tool calls exists."""
    last_message = state["messages"][-1]

    tool_calls = getattr(last_message, "tool_calls", None)

    if isinstance(tool_calls, list) and len(tool_calls) > 0:
        return "tools"

    return "__end__"


def create_agent_graph(
    checkpointer: AsyncPostgresSaver | None = None,
) -> Any:
    """Build and compile the LangGraph workflow."""
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", guardrails_and_tools_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "__end__": END,
        },
    )

    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer)
from collections.abc import Sequence
from typing import Annotated, Any
import uuid

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class ToolExecutionRecord(TypedDict):
    tool_name: str
    tool_args: dict[str, Any]
    output: Any
    timestamp: str


class AgentState(TypedDict):
    """
    LangGraph dynamic state passed across execution nodes.
    Maintains full type safety and message append semantics.
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: uuid.UUID
    current_thread_id: str
    tool_call_history: list[ToolExecutionRecord]
    pending_confirmation: bool
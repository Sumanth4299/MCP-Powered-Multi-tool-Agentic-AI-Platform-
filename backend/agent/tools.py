
import json
import uuid
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model

from backend.mcp.client import MCPTaskClientAdapter
from mcp_servers.calendar_server import mcp as calendar_mcp
from mcp_servers.holiday_server import mcp as holiday_mcp
from mcp_servers.task_server import mcp as task_mcp


def make_pydantic_model(
    schema: dict[str, Any],
    name: str,
) -> type[BaseModel]:
    """Dynamically reconstruct a Pydantic schema from an MCP tool JSON schema."""

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}

    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    for prop_name, prop_data in properties.items():
        prop_type = type_mapping.get(
            prop_data.get("type", "string"),
            Any,
        )

        is_required = prop_name in required
        default_val = (
            ...
            if is_required
            else prop_data.get("default", None)
        )

        fields[prop_name] = (
            prop_type if is_required else prop_type | None,
            default_val,
        )

    return create_model(f"{name}Input", **fields)


def convert_fastmcp_to_langchain(
    tool: Any,
    server: Any,
    user_id: uuid.UUID | None = None,
) -> StructuredTool:
    """
    Convert a FastMCP tool into a LangChain StructuredTool.

    User-scoped servers receive the authenticated user ID at execution time.
    """

    name = tool.name
    description = tool.description or f"MCP tool: {name}"

    # Extract the input schema exposed by the FastMCP tool.
    input_schema = getattr(tool, "inputSchema", None)

    if input_schema is None:
        input_schema = getattr(tool, "input_schema", None)

    if input_schema is None:
        input_schema = {}

    args_schema = make_pydantic_model(input_schema, name)

    async def _coro(**kwargs: Any) -> str:
        arguments = dict(kwargs)

        if user_id is not None:
            arguments["user_id"] = str(user_id)

        # Invoke the registered FastMCP tool.
        result = await server._tool_manager.call_tool(
            name,
            arguments,
        )

        if isinstance(result, str):
            return result

        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")

        return json.dumps(result, default=str)

    return StructuredTool(
        name=name,
        description=description,
        coroutine=_coro,
        args_schema=args_schema,
    )


async def get_federated_tools(user_id: uuid.UUID) -> list[StructuredTool]:
    tools: list[StructuredTool] = []

    # FastMCP exposes async list_tools()
    holiday_tools = await holiday_mcp.list_tools()
    for tool in holiday_tools:
        tools.append(convert_fastmcp_to_langchain(tool, holiday_mcp))

    task_tools = await task_mcp.list_tools()
    for tool in task_tools:
        tools.append(convert_fastmcp_to_langchain(tool, task_mcp, user_id=user_id))

    cal_tools = await calendar_mcp.list_tools()
    for tool in cal_tools:
        tools.append(convert_fastmcp_to_langchain(tool, calendar_mcp, user_id=user_id))

    return tools


async def get_langchain_mcp_tools(
    client_adapter: MCPTaskClientAdapter,
    user_id: uuid.UUID,
) -> list[StructuredTool]:
    """
    Retain the existing client-adapter-based tool loading functionality.
    """

    raw_tools = await client_adapter.list_available_tools(
        user_id=user_id,
    )

    langchain_tools: list[StructuredTool] = []

    for tool in raw_tools:
        name = tool["name"]
        description = tool["description"]
        input_schema = tool["input_schema"]

        args_schema = make_pydantic_model(
            input_schema,
            name,
        )

        def make_tool_fn(tool_name: str):
            async def _coro(**kwargs: Any) -> str:
                result = await client_adapter.execute_tool(
                    user_id=user_id,
                    tool_name=tool_name,
                    arguments=kwargs,
                )

                return (
                    result
                    if isinstance(result, str)
                    else json.dumps(result, default=str)
                )

            return _coro

        langchain_tools.append(
            StructuredTool(
                name=name,
                description=description,
                coroutine=make_tool_fn(name),
                args_schema=args_schema,
            )
        )

    return langchain_tools
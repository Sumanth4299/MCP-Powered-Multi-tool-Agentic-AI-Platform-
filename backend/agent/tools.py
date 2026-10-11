
import json
import uuid
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model

from backend.mcp.client import MCPTaskClientAdapter
from mcp_servers.calendar_server import (
    current_user_id_ctx as calendar_user_id_ctx,
    mcp as calendar_mcp,
)
from mcp_servers.holiday_server import mcp as holiday_mcp
from mcp_servers.task_server import (
    current_user_id_ctx as task_user_id_ctx,
    mcp as task_mcp,
)


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
        input_schema = getattr(tool, "parameters", None)

    if input_schema is None:
        input_schema = {}

    properties = input_schema.get("properties", {})
    if "ctx" in properties:
        input_schema = {
            **input_schema,
            "properties": {
                key: value for key, value in properties.items() if key != "ctx"
            },
            "required": [
                key for key in input_schema.get("required", []) if key != "ctx"
            ],
        }

    args_schema = make_pydantic_model(input_schema, name)
    tool_param_names = input_schema.get("properties", {}).keys()

    async def _coro(**kwargs: Any) -> str:
        arguments = dict(kwargs)

        if user_id is not None and "user_id" in tool_param_names:
            arguments["user_id"] = str(user_id)
        elif arguments.get("user_id") is None:
            arguments.pop("user_id", None)

        context_tokens = []
        if user_id is not None and server is task_mcp:
            context_tokens.append((task_user_id_ctx, task_user_id_ctx.set(user_id)))
        elif user_id is not None and server is calendar_mcp:
            context_tokens.append((calendar_user_id_ctx, calendar_user_id_ctx.set(user_id)))

        try:
            # Invoke through FastMCP's public API when available.
            result: Any
            if hasattr(server, "call_tool"):
                result = await server.call_tool(name=name, arguments=arguments)
            elif hasattr(server, "_tool_manager"):
                result = await server._tool_manager.call_tool(name, arguments)
            else:
                raise AttributeError(
                    f"Server {server} has neither 'call_tool' nor '_tool_manager'."
                )
        finally:
            for context_var, token in reversed(context_tokens):
                context_var.reset(token)

        if not isinstance(result, (str, dict)):
            content = getattr(result, "content", None)
            if isinstance(content, list):
                result = content

        if isinstance(result, list):
            extracted = []
            for item in result:
                if hasattr(item, "text"):
                    extracted.append(item.text)
                elif isinstance(item, dict) and "text" in item:
                    extracted.append(item["text"])
                else:
                    extracted.append(str(item))
            result = "\n".join(extracted)

        if isinstance(result, str):
            return result

        model_dump = getattr(result, "model_dump", None)
        if callable(model_dump):
            result = model_dump(mode="json")

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
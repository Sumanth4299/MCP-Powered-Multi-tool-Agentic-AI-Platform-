"""
MCP Client Adapter: Connects the agent orchestration loop to the FastMCP Task Server.
Handles transport handshakes and injects authenticated user identity headers.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
import sys
from typing import Any
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

from mcp_servers.task_server import current_user_id_ctx


class MCPTaskClientAdapter:
    """
    Adapter exposing methods to connect to the MCP Task Server,
    bind the authenticated user session context, and invoke tools.
    """

    def __init__(self, transport_type: str = "stdio", server_url: str | None = None):
        self.transport_type = transport_type
        self.server_url = server_url or "http://localhost:8001/sse"

    @asynccontextmanager
    async def get_session(
        self,
        user_id: uuid.UUID,
    ) -> AsyncIterator[ClientSession]:
        """
        Context manager returning an authenticated ClientSession.
        Ensures `user_id` is bound to the transport session without LLM visibility.
        """
        if self.transport_type == "sse":
            # SSE Transport: pass user_id as an authenticated header
            headers = {"x-user-id": str(user_id)}
            async with sse_client(self.server_url, headers=headers) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session

        elif self.transport_type == "stdio":
            # Stdio Transport: pass user_id via process environment + context variable
            env = os.environ.copy()
            env["MCP_USER_ID"] = str(user_id)

            server_params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "mcp_servers.task_server"],
                env=env,
            )
            # Set the contextvar for in-process/direct callers
            token = current_user_id_ctx.set(user_id)
            try:
                async with stdio_client(server_params) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        yield session
            finally:
                current_user_id_ctx.reset(token)
        else:
            raise ValueError(f"Unsupported MCP transport: {self.transport_type}")

    # backend/mcp/client.py

    async def list_available_tools(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        async with self.get_session(user_id) as session:
            tools_result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    # Fallback handles both SDK camelCase and snake_case models
                    "input_schema": getattr(tool, "input_schema", getattr(tool, "inputSchema", {})),
                }
                for tool in tools_result.tools
            ]

    async def execute_tool(
        self,
        user_id: uuid.UUID,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Execute a tool on behalf of the authenticated user."""
        async with self.get_session(user_id) as session:
            result = await session.call_tool(tool_name, arguments=arguments)
            # Unpack first text element from MCP call result
            if result.content and result.content[0].type == "text":
                return result.content[0].text
            return result.content
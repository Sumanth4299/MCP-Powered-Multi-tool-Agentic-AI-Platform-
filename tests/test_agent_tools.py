import pytest

from backend.agent.tools import convert_fastmcp_to_langchain


def _tool():
    return type(
        "Tool",
        (),
        {
            "name": "sample_tool",
            "description": "Sample tool",
            "inputSchema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    )()


def _fastmcp_tool():
    return type(
        "Tool",
        (),
        {
            "name": "sample_tool",
            "description": "Sample tool",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "user_id": {"type": "string"},
                    "ctx": {"default": None},
                },
                "required": ["title"],
            },
        },
    )()


@pytest.mark.asyncio
async def test_convert_tool_uses_public_server_call_tool() -> None:
    class Server:
        async def call_tool(self, *, name, arguments):
            assert name == "sample_tool"
            assert arguments == {"value": "hello"}
            return {"result": "ok"}

    converted = convert_fastmcp_to_langchain(_tool(), Server())

    assert await converted.ainvoke({"value": "hello"}) == '{"result": "ok"}'


@pytest.mark.asyncio
async def test_convert_tool_extracts_text_from_content_block_lists() -> None:
    class TextBlock:
        text = "first"

    class Server:
        async def call_tool(self, *, name, arguments):
            return [TextBlock(), {"text": "second"}, 3]

    converted = convert_fastmcp_to_langchain(_tool(), Server())

    assert await converted.ainvoke({"value": "hello"}) == "first\nsecond\n3"


@pytest.mark.asyncio
async def test_convert_tool_extracts_content_from_fastmcp_result_object() -> None:
    class TextBlock:
        text = "tool response"

    class ToolResult:
        content = [TextBlock()]

    class Server:
        async def call_tool(self, *, name, arguments):
            return ToolResult()

    converted = convert_fastmcp_to_langchain(_tool(), Server())

    assert await converted.ainvoke({"value": "hello"}) == "tool response"


@pytest.mark.asyncio
async def test_convert_tool_falls_back_to_tool_manager() -> None:
    class ToolManager:
        async def call_tool(self, name, arguments):
            assert name == "sample_tool"
            assert arguments == {"value": "hello"}
            return "ok"

    class Server:
        _tool_manager = ToolManager()

    converted = convert_fastmcp_to_langchain(_tool(), Server())

    assert await converted.ainvoke({"value": "hello"}) == "ok"


@pytest.mark.asyncio
async def test_convert_tool_errors_when_server_cannot_invoke() -> None:
    converted = convert_fastmcp_to_langchain(_tool(), object())

    with pytest.raises(AttributeError, match="neither 'call_tool' nor '_tool_manager'"):
        await converted.ainvoke({"value": "hello"})


@pytest.mark.asyncio
async def test_convert_tool_includes_user_id_in_server_arguments() -> None:
    import uuid

    user_id = uuid.uuid4()

    class Server:
        async def call_tool(self, *, name, arguments):
            assert arguments == {
                "title": "Workout",
                "user_id": str(user_id),
            }
            return "ok"

    converted = convert_fastmcp_to_langchain(
        _fastmcp_tool(), Server(), user_id=user_id
    )

    assert await converted.ainvoke({"title": "Workout"}) == "ok"


@pytest.mark.asyncio
async def test_fastmcp_parameters_schema_preserves_required_arguments() -> None:
    class Server:
        async def call_tool(self, *, name, arguments):
            assert name == "sample_tool"
            assert arguments == {"title": "Workout"}
            return "ok"

    converted = convert_fastmcp_to_langchain(_fastmcp_tool(), Server())

    assert set(converted.args_schema.model_fields) == {"title", "user_id"}
    assert await converted.ainvoke({"title": "Workout"}) == "ok"


@pytest.mark.asyncio
async def test_task_user_id_uses_context_not_tool_arguments(monkeypatch) -> None:
    import uuid

    from backend.agent.tools import task_mcp, task_user_id_ctx

    user_id = uuid.uuid4()
    previous_user_id = task_user_id_ctx.get()
    seen_arguments = {}

    async def mock_call_tool(*, name, arguments):
        assert task_user_id_ctx.get() == user_id
        seen_arguments.update(arguments)
        return "ok"

    monkeypatch.setattr(task_mcp, "call_tool", mock_call_tool)
    converted = convert_fastmcp_to_langchain(_tool(), task_mcp, user_id=user_id)

    try:
        assert await converted.ainvoke({"value": "hello"}) == "ok"
        assert seen_arguments == {"value": "hello"}
        assert task_user_id_ctx.get() == previous_user_id
    finally:
        task_user_id_ctx.set(previous_user_id)

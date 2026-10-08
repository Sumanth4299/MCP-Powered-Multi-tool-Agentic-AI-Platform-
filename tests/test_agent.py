from collections.abc import AsyncGenerator
import json
import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["SECRET_KEY"] = "test-secret-key-32-characters-long-minimum-abc123"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GEMINI_API_KEY"] = "mock_gemini_api_key"

from backend.api.deps import get_current_user
from backend.database import get_db
from backend.main import app
from backend.models.base import Base
from backend.models.user import User
from backend.services.task_service import TaskService
from mcp_servers.task_server import current_user_id_ctx

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    import backend.database

    import mcp_servers.task_server

    backend.database.async_session_factory = TestingSessionLocal
    mcp_servers.task_server.async_session_factory = TestingSessionLocal

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def mock_user() -> User:
    async with TestingSessionLocal() as session:
        user = User(
            id=uuid.uuid4(),
            name="Agent Student",
            email="student@example.com",
            password_hash="hashed_pw",
            timezone="UTC",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def authed_client(mock_user: User) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_current_user() -> User:
        return mock_user

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_agent_graph_multi_turn_and_destructive_guardrail(mock_user: User, monkeypatch):
    """
    Validates agent graph behavior:
    1. Gemini returns a tool call to delete a task without confirmation.
    2. Guardrails node intercepts and rejects the destructive action.
    3. Gemini requests user confirmation.
    """
    current_user_id_ctx.set(mock_user.id)

    # Pre-populate a task
    async with TestingSessionLocal() as session:
        from backend.schemas.task import TaskCreate
        task = await TaskService.create_task(
            db=session,
            user_id=mock_user.id,
            data=TaskCreate(title="Database Systems Report"),
        )
        task_id = str(task.id)

    # Mock Gemini behavior: first attempts delete_task with confirm=False, then asks user
    mock_responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "delete_task",
                "args": {"task_id": task_id, "confirm": False},
                "id": "call_1",
            }],
        ),
        AIMessage(
            content="Deleting your 'Database Systems Report' task is permanent. Are you sure you want to delete it?",
        ),
    ]

    call_index = 0

    async def mock_ainvoke(*args, **kwargs):
        nonlocal call_index
        res = mock_responses[call_index]
        call_index += 1
        return res

    import backend.agent.graph as graph_module
    monkeypatch.setattr(graph_module, "build_llm", lambda tools: type("MockLLM", (), {"ainvoke": mock_ainvoke})())

    from backend.agent.graph import create_agent_graph
    from langchain_core.messages import HumanMessage

    graph = create_agent_graph()
    state = {
        "messages": [HumanMessage(content="Delete my Database Systems Report task.")],
        "user_id": mock_user.id,
        "current_thread_id": "test_thread",
        "tool_call_history": [],
        "pending_confirmation": False,
    }

    result = await graph.ainvoke(state)

    # Verify that the action was blocked and logged
    assert len(result["tool_call_history"]) == 1
    assert "Action Blocked" in result["tool_call_history"][0]["output"]
    assert "Are you sure you want to delete it?" in result["messages"][-1].content


@pytest.mark.asyncio
async def test_cross_chat_retrieval(authed_client: AsyncClient, mock_user: User):
    """
    Verifies that tasks created outside of a conversation or in an earlier thread
    are discoverable via tools by a new thread.
    """
    current_user_id_ctx.set(mock_user.id)

    # 1. Create a task via TaskService (as if created in Thread A or via REST API)
    async with TestingSessionLocal() as session:
        from backend.schemas.task import TaskCreate
        await TaskService.create_task(
            db=session,
            user_id=mock_user.id,
            data=TaskCreate(title="Prepare Final Year Defense Slides"),
        )

    # 2. Open Thread B
    create_convo_res = await authed_client.post("/conversations", json={"title": "Thread B"})
    assert create_convo_res.status_code == 201
    thread_b_id = create_convo_res.json()["thread_id"]

    # 3. Query tool directly to confirm cross-chat discovery
    from mcp_servers.task_server import search_tasks
    search_res = await search_tasks(query="Defense Slides")
    tasks = json.loads(search_res)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Prepare Final Year Defense Slides"
"""
End-to-end integration tests for the FastMCP Task Server.
Verifies safety confirmation flags, input validation, and user context isolation.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
import json
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set up test environment
os.environ["SECRET_KEY"] = "test-secret-key-32-characters-long-minimum-abc123"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from backend.models.base import Base
from backend.models.user import User
from mcp_servers.task_server import (
    complete_task,
    create_task,
    current_user_id_ctx,
    delete_task,
    get_task,
    list_tasks,
    search_tasks,
    update_task,
)

test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def init_db():
    import backend.database
    import mcp_servers.task_server

    # Patch session factories that actually instantiate connections
    backend.database.async_session_factory = TestSession
    mcp_servers.task_server.async_session_factory = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def sample_user() -> User:
    async with TestSession() as session:
        user = User(
            id=uuid.uuid4(),
            name="MCP Tester",
            email="tester@example.com",
            password_hash="mock_hash",
            timezone="UTC",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def other_user() -> User:
    async with TestSession() as session:
        user = User(
            id=uuid.uuid4(),
            name="Other Tenant",
            email="other@example.com",
            password_hash="mock_hash",
            timezone="UTC",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_mcp_create_and_list_tasks(sample_user: User):
    token = current_user_id_ctx.set(sample_user.id)
    try:
        # 1. Create task via tool
        raw_res = await create_task(
            title="Deploy FastMCP Server",
            description="Expose tool schemas for Agent Phase 3",
            due_at="2026-10-25T15:00:00Z",
            priority="high",
        )
        data = json.loads(raw_res)
        assert data["title"] == "Deploy FastMCP Server"
        assert data["priority"] == "high"
        assert data["source"] == "mcp_agent"
        task_id = data["id"]

        # 2. List tasks via tool
        list_raw = await list_tasks(priority="high")
        tasks = json.loads(list_raw)
        assert len(tasks) == 1
        assert tasks[0]["id"] == task_id

        # 3. Search tasks via tool
        search_raw = await search_tasks(query="FastMCP")
        results = json.loads(search_raw)
        assert len(results) == 1
        assert results[0]["id"] == task_id
    finally:
        current_user_id_ctx.reset(token)


@pytest.mark.asyncio
async def test_mcp_update_and_complete_task(sample_user: User):
    token = current_user_id_ctx.set(sample_user.id)
    try:
        raw = await create_task(title="Incomplete Task", priority="low")
        task_id = json.loads(raw)["id"]

        # Update
        update_raw = await update_task(
            task_id=task_id,
            title="Updated Title",
            priority="medium",
        )
        updated_data = json.loads(update_raw)
        assert updated_data["title"] == "Updated Title"
        assert updated_data["priority"] == "medium"

        # Complete
        comp_raw = await complete_task(task_id=task_id)
        comp_data = json.loads(comp_raw)
        assert comp_data["status"] == "completed"
        assert comp_data["completed_at"] is not None
    finally:
        current_user_id_ctx.reset(token)


@pytest.mark.asyncio
async def test_mcp_delete_safety_guardrail(sample_user: User):
    token = current_user_id_ctx.set(sample_user.id)
    try:
        raw = await create_task(title="Task to delete")
        task_id = json.loads(raw)["id"]

        # 1. Attempt delete without confirmation
        blocked_raw = await delete_task(task_id=task_id, confirm=False)
        blocked_data = json.loads(blocked_raw)
        assert blocked_data["status"] == "confirmation_required"

        # Verify task still exists
        verify_raw = await get_task(task_id=task_id)
        assert "error" not in json.loads(verify_raw)

        # 2. Delete with explicit confirmation
        success_raw = await delete_task(task_id=task_id, confirm=True)
        assert json.loads(success_raw)["status"] == "success"

        # Verify task is soft-deleted
        deleted_raw = await get_task(task_id=task_id)
        assert "error" in json.loads(deleted_raw)
    finally:
        current_user_id_ctx.reset(token)


@pytest.mark.asyncio
async def test_mcp_unauthenticated_fails():
    # Attempting to call tools without setting user context raises PermissionError
    current_user_id_ctx.set(None)
    with pytest.raises(PermissionError, match="Unauthenticated MCP tool execution context"):
        await list_tasks()


@pytest.mark.asyncio
async def test_mcp_cross_tenant_isolation(sample_user: User, other_user: User):
    # User A creates a task
    token_a = current_user_id_ctx.set(sample_user.id)
    raw = await create_task(title="User A Secret Task")
    task_a_id = json.loads(raw)["id"]
    current_user_id_ctx.reset(token_a)

    # User B attempts to access and modify User A's task
    token_b = current_user_id_ctx.set(other_user.id)
    try:
        # Get should fail
        get_res = json.loads(await get_task(task_id=task_a_id))
        assert "error" in get_res

        # Complete should fail
        comp_res = json.loads(await complete_task(task_id=task_a_id))
        assert "error" in comp_res

        # Delete should fail
        del_res = json.loads(await delete_task(task_id=task_a_id, confirm=True))
        assert "error" in del_res

        # Search should return empty
        search_res = json.loads(await search_tasks(query="Secret"))
        assert len(search_res) == 0
    finally:
        current_user_id_ctx.reset(token_b)
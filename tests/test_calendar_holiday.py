from datetime import datetime, timezone
import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["SECRET_KEY"] = "test-secret-key-32-characters-long-minimum-abc123"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENCRYPTION_KEY"] = "t_h-XyZ1234567890abcdefghijklmnopqrstuvwxyz="

from backend.models.base import Base
from backend.models.integration import IntegrationSettings
from backend.models.user import User
from backend.services.crypto_service import encrypt_token
from mcp_servers.calendar_server import (
    check_calendar_availability,
    current_user_id_ctx,
    get_calendar_events,
)
from mcp_servers.holiday_server import check_holidays

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def init_db():
    import backend.database
    backend.database.async_session_factory = TestSession

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def user_with_google_integration() -> User:
    async with TestSession() as session:
        user = User(
            id=uuid.uuid4(),
            name="Calendar User",
            email="caluser@example.com",
            password_hash="mock",
            timezone="Asia/Kolkata",
        )
        session.add(user)
        await session.flush()

        integration = IntegrationSettings(
            user_id=user.id,
            provider="google",
            encrypted_refresh_token=encrypt_token("mock_refresh_token_12345"),
            scope="https://www.googleapis.com/auth/calendar.readonly",
        )
        session.add(integration)
        await session.commit()
        await session.refresh(user)
        return user


# --- Holiday Server Tests ---

@pytest.mark.asyncio
async def test_check_holidays_known_gazetted():
    # Mahatma Gandhi Jayanti 2026-10-02
    res = await check_holidays(date="2026-10-02", region="India")
    data = json.loads(res)
    assert data["is_holiday"] is True
    assert any("Gandhi Jayanti" in h["name"] for h in data["holidays"])


@pytest.mark.asyncio
async def test_check_holidays_state_specific():
    # Telangana Formation Day 2026-06-02
    res_tg = await check_holidays(date="2026-06-02", region="Telangana")
    data_tg = json.loads(res_tg)
    assert data_tg["is_holiday"] is True
    assert "Telangana Formation Day" in data_tg["holidays"][0]["name"]


@pytest.mark.asyncio
async def test_check_holidays_working_day():
    res = await check_holidays(date="2026-10-05", region="India")
    data = json.loads(res)
    assert data["is_holiday"] is False


# --- Google Calendar Server Tests (Mocked API) ---

@pytest.mark.asyncio
async def test_get_calendar_events_mocked(user_with_google_integration: User):
    token = current_user_id_ctx.set(user_with_google_integration.id)

    mock_service = MagicMock()
    mock_events = {
        "items": [
            {
                "id": "event_1",
                "summary": "Project Review Meeting",
                "start": {"dateTime": "2026-10-05T10:00:00+05:30"},
                "end": {"dateTime": "2026-10-05T11:00:00+05:30"},
            }
        ]
    }
    mock_service.events().list().execute.return_value = mock_events

    with patch("mcp_servers.calendar_server._get_calendar_service", return_value=mock_service):
        try:
            raw_res = await get_calendar_events(
                start_date="2026-10-05T00:00:00Z",
                end_date="2026-10-05T23:59:59Z",
            )
            data = json.loads(raw_res)
            assert len(data) == 1
            assert data[0]["summary"] == "Project Review Meeting"
            assert data[0]["id"] == "event_1"
        finally:
            current_user_id_ctx.reset(token)


@pytest.mark.asyncio
async def test_check_calendar_availability_mocked(user_with_google_integration: User):
    token = current_user_id_ctx.set(user_with_google_integration.id)

    mock_service = MagicMock()
    mock_freebusy = {
        "calendars": {
            "primary": {
                "busy": [
                    {
                        "start": "2026-10-05T14:00:00Z",
                        "end": "2026-10-05T15:30:00Z",
                    }
                ]
            }
        }
    }
    mock_service.freebusy().query().execute.return_value = mock_freebusy

    with patch("mcp_servers.calendar_server._get_calendar_service", return_value=mock_service):
        try:
            raw_res = await check_calendar_availability(
                start_date="2026-10-05T09:00:00Z",
                end_date="2026-10-05T18:00:00Z",
            )
            data = json.loads(raw_res)
            assert data["is_completely_free"] is False
            assert len(data["busy_intervals"]) == 1
            assert data["busy_intervals"][0]["start"] == "2026-10-05T14:00:00Z"
        finally:
            current_user_id_ctx.reset(token)
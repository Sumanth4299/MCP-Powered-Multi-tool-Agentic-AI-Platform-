"""
FastMCP Google Calendar Server.
Provides read-only inspection of Google Calendar events and availability slots.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from typing import Any
import uuid

try:
    from mcp.server.fastmcp import FastMCP, Context  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    from fastmcp import FastMCP, Context  # type: ignore[no-redef]
from sqlalchemy import select

from backend.config import get_settings
from backend.database import async_session_factory
from backend.models.integration import IntegrationSettings
from backend.services.crypto_service import decrypt_token

settings = get_settings()

mcp = FastMCP(
    name="Google Calendar Server",
    instructions="Read-only tools for inspecting scheduled calendar events and identifying free slots.",
)

current_user_id_ctx: ContextVar[uuid.UUID | None] = ContextVar("calendar_user_id", default=None)


def _resolve_user_id(ctx: Context) -> uuid.UUID:
    if hasattr(ctx, "session") and ctx.session is not None:
        meta = getattr(ctx.session, "metadata", {}) or {}
        uid = meta.get("user-id") or meta.get("x-user-id")
        if uid:
            return uuid.UUID(str(uid))

    bound_id = current_user_id_ctx.get()
    if bound_id:
        return bound_id
    raise PermissionError("Unauthenticated Google Calendar MCP context.")


async def _get_calendar_service(user_id: uuid.UUID):
    """Decrypts user refresh token and constructs Google Calendar API v3 service."""
    async with async_session_factory() as db:
        stmt = select(IntegrationSettings).where(
            IntegrationSettings.user_id == user_id,
            IntegrationSettings.provider == "google",
        )
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

    if not record:
        raise ValueError("Google Calendar is not linked. User must authenticate via /integrations/google/connect.")

    refresh_token = decrypt_token(record.encrypted_refresh_token)
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=record.scope.split(" "),
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


@mcp.tool(
    name="get_calendar_events",
    description="List confirmed calendar events between two ISO 8601 dates on user's primary Google Calendar.",
)
async def get_calendar_events(
    start_date: str,
    end_date: str,
    ctx: Any = None,
) -> str:
    """
    Args:
        start_date: ISO 8601 formatted start window (e.g., '2026-10-05T00:00:00Z').
        end_date: ISO 8601 formatted end window (e.g., '2026-10-05T23:59:59Z').
    """
    user_id = _resolve_user_id(ctx)
    try:
        service = await _get_calendar_service(user_id)
    except Exception as e:
        return json.dumps({"error": str(e)})

    # Format bounds
    t_min = start_date.replace("Z", "+00:00")
    t_max = end_date.replace("Z", "+00:00")

    events_result = service.events().list(
        calendarId="primary",
        timeMin=t_min,
        timeMax=t_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    items = events_result.get("items", [])
    simplified = []
    for item in items:
        simplified.append({
            "id": item.get("id"),
            "summary": item.get("summary", "Busy"),
            "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
            "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
        })

    return json.dumps(simplified, indent=2)


@mcp.tool(
    name="check_calendar_availability",
    description="Query free/busy intervals between two dates to find open scheduling windows.",
)
async def check_calendar_availability(
    start_date: str,
    end_date: str,
    ctx: Any = None,
) -> str:
    """
    Args:
        start_date: ISO 8601 string for beginning of evaluation window.
        end_date: ISO 8601 string for end of evaluation window.
    """
    user_id = _resolve_user_id(ctx)
    try:
        service = await _get_calendar_service(user_id)
    except Exception as e:
        return json.dumps({"error": str(e)})

    body = {
        "timeMin": start_date.replace("Z", "+00:00"),
        "timeMax": end_date.replace("Z", "+00:00"),
        "items": [{"id": "primary"}],
    }

    freebusy = service.freebusy().query(body=body).execute()
    busy_slots = freebusy.get("calendars", {}).get("primary", {}).get("busy", [])

    return json.dumps({
        "evaluation_range": {"start": start_date, "end": end_date},
        "busy_intervals": busy_slots,
        "is_completely_free": len(busy_slots) == 0,
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
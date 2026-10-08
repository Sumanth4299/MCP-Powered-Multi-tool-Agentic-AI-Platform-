from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.config import get_settings
from backend.database import get_db
from backend.models.integration import IntegrationSettings
from backend.models.user import User
from backend.services.crypto_service import encrypt_token

router = APIRouter(prefix="/integrations", tags=["Integrations"])
settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]


def _build_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


@router.get("/google/connect")
async def google_connect(current_user: User = Depends(get_current_user)) -> dict[str, str]:
    """Initiates Google OAuth2 flow using user_id as state parameter."""
    flow = _build_flow(state=str(current_user.id))
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"authorization_url": auth_url}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchanges authorization code for tokens and saves encrypted refresh token."""
    flow = _build_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token exchange failed: {str(e)}",
        )

    credentials = flow.credentials
    if not credentials.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No refresh token returned. Revoke permissions at Google and reconnect.",
        )

    import uuid
    user_id = uuid.UUID(state)

    stmt = select(IntegrationSettings).where(
        IntegrationSettings.user_id == user_id,
        IntegrationSettings.provider == "google",
    )
    res = await db.execute(stmt)
    integration = res.scalar_one_or_none()

    encrypted = encrypt_token(credentials.refresh_token)
    joined_scopes = " ".join(credentials.scopes or SCOPES)

    if integration:
        integration.encrypted_refresh_token = encrypted
        integration.scope = joined_scopes
    else:
        integration = IntegrationSettings(
            user_id=user_id,
            provider="google",
            encrypted_refresh_token=encrypted,
            scope=joined_scopes,
        )
        db.add(integration)

    await db.commit()
    return {"status": "success", "message": "Google Calendar successfully connected."}
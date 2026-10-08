from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.user import User
from backend.schemas.auth import UserRegister

settings = get_settings()

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=4,
)


def hash_password(password: str) -> str:
    """Compute an Argon2id salted hash for a plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify input password against an Argon2id hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: uuid.UUID,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """
    Generate a cryptographically signed HMAC-SHA256 JWT containing user subject.
    Returns a tuple of (token_string, expires_in_seconds).
    """
    now = datetime.now(timezone.utc)
    duration = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + duration

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(duration.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate JWT expiration and signature.
    Raises jwt.PyJWTError subclasses on failure.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"require": ["sub", "iat", "exp"]},
    )


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Fetch user by case-insensitive unique email."""
    stmt = select(User).where(User.email == email.lower().strip())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Fetch user by primary key UUID."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def register_new_user(db: AsyncSession, user_in: UserRegister) -> User:
    """Create and persist a new user record with an Argon2id password hash."""
    new_user = User(
        name=user_in.name.strip(),
        email=user_in.email.lower().strip(),
        password_hash=hash_password(user_in.password),
        timezone=user_in.timezone,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """Authenticate credentials against stored hash."""
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
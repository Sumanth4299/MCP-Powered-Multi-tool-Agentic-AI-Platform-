import uuid
from sqlalchemy import ForeignKey, Index, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class IntegrationSettings(Base, TimestampMixin):
    """
    Stores encrypted OAuth2 refresh tokens and scopes per provider.
    Guarantees strict foreign-key tenant scoping.
    """
    __tablename__ = "integration_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    encrypted_refresh_token: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_user_provider", "user_id", "provider", unique=True),
    )
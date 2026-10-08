# backend/config.py
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application runtime configuration loaded from environment variables
    with strict type safety via Pydantic Settings v2.
    """
    ENVIRONMENT: str = Field(default="development", description="Environment stage")
    DEBUG: bool = Field(default=False, description="Debug mode flag")

    # PostgreSQL Database URL
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/productivity_agent",
        description="Async PostgreSQL connection URI",
    )

    # JWT Security Configurations
    SECRET_KEY: str = Field(
        default="",
        description="HMAC secret key used for signing JWTs",
    )
    ALGORITHM: str = Field(
        default="HS256",
        description="Symmetric signing algorithm",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24,
        description="JWT expiration TTL in minutes",
    )

    # Google Gemini & LLM settings
    GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API key",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model variant",
    )

    # Cryptography / Token Encryption
    ENCRYPTION_KEY: str = Field(
        default="t_h-XyZ1234567890abcdefghijklmnopqrstuvwxyz=",
        description="Fernet key for decrypting OAuth tokens",
    )

    # Google OAuth2 Settings (Resolves Pylance attribute access errors)
    GOOGLE_CLIENT_ID: str = Field(
        default="",
        description="Google Cloud OAuth2 Client ID",
    )
    GOOGLE_CLIENT_SECRET: str = Field(
        default="",
        description="Google Cloud OAuth2 Client Secret",
    )
    GOOGLE_REDIRECT_URI: str = Field(
        default="http://localhost:8000/integrations/google/callback",
        description="Google Cloud OAuth2 Authorized Redirect URI",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
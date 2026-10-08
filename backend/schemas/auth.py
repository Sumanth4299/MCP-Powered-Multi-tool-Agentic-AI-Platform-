from datetime import datetime
from uuid import UUID
import zoneinfo
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=8, max_length=128)
    timezone: str = Field(default="UTC", max_length=50)

    @field_validator("timezone")
    @classmethod
    def validate_iana_timezone(cls, value: str) -> str:
        if value not in zoneinfo.available_timezones():
            raise ValueError(f"'{value}' is not a recognized IANA timezone identifier.")
        return value


class UserLogin(BaseModel):
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    timezone: str
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
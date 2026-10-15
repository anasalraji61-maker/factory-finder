"""Request/response models for gateway-owned endpoints."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Role = Literal["buyer", "supplier", "both"]
Language = Literal["ar", "en"]
_COMMON_PASSWORDS = frozenset({
    "password", "passw0rd", "12345678", "123456789", "1234567890", "11111111", "00000000", "qwertyui", "qwerty123",
    "abcd1234", "iloveyou", "letmein1", "admin123", "welcome1", "87654321", "password1",
})  # deliberately tiny: blocks the worst offenders without a dictionary dependency (NIST 800-63B spirit)
_PHONE = re.compile(r"^\+?\d{7,15}$")


def normalize_phone(v: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", v)
    if not _PHONE.match(cleaned):
        raise ValueError("phone must be 7-15 digits, optional leading +")
    return cleaned


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Location(BaseModel):
    country_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    city: str | None = Field(default=None, max_length=120)
    point: GeoPoint | None = None


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr | None = None
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.lower() if v else None

    @model_validator(mode="after")
    def _one_contact(self) -> "RegisterIn":
        if not self.email and not self.phone:
            raise ValueError("either email or phone is required")
        low = self.password.lower()
        local = (self.email or "").split("@")[0]
        if (
            low in _COMMON_PASSWORDS
            or len(set(low)) < 3
            or low == (self.email or "") or (len(local) >= 6 and low == local)
            or (self.phone and low.lstrip("+") == self.phone.lstrip("+"))
        ):
            raise ValueError("password is too easy to guess")
        return self


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr | None = None
    phone: str | None = None
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.lower() if v else None  # registration stores lowercase; "Bob@X.com" must find "bob@x.com"

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None

    @model_validator(mode="after")
    def _one_contact(self) -> "LoginIn":
        if not self.email and not self.phone:
            raise ValueError("either email or phone is required")
        return self


class RefreshIn(BaseModel):
    refresh_token: str


class MeOut(BaseModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    role: Role
    default_destination: Location | None = None
    supplier_id: str | None = None
    supplier_claim_status: Literal["none", "pending", "verified"] = "none"
    email_verified: bool = False
    display_currency: str
    language: Language
    created_at: datetime


class VerifyEmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200)


class ResendVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower()


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: MeOut | None = None


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    default_destination: Location | None = None
    display_currency: Annotated[str | None, Field(pattern=r"^[A-Z]{3}$")] = None
    language: Language | None = None
    supplier_id: Annotated[str | None, Field(pattern=r"^sup_[A-Za-z0-9_.:\-]{1,59}$")] = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.lower() if v else v


class DeleteAccountIn(BaseModel):
    """Re-authentication for account deletion: the current password, or a current (unused) refresh token."""

    model_config = ConfigDict(extra="forbid")
    password: str | None = Field(default=None, min_length=1, max_length=200)
    refresh_token: str | None = Field(default=None, min_length=10, max_length=2000)

    @model_validator(mode="after")
    def _one_proof(self) -> "DeleteAccountIn":
        if not (self.password or self.refresh_token):
            raise ValueError("password or refresh_token is required")
        return self

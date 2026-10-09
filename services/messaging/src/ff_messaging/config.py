"""Service configuration (environment prefix ``FF_MESSAGING_``)."""

import json
from functools import cached_property
from typing import Annotated, Any

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ff_messaging.domain.ids import is_valid_user_id
from ff_messaging.domain.models import AbuseAction

DEFAULT_ATTACHMENT_MIME_TYPES: tuple[str, ...] = (
    # images (no SVG: it can carry scripts when rendered by web clients)
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    # documents
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    # media
    "video/mp4",
    "video/quicktime",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
)

StrList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """All knobs of the messaging service. List values accept a JSON array or a comma list."""

    model_config = SettingsConfigDict(
        env_prefix="FF_MESSAGING_",
        extra="ignore",
        populate_by_name=True,
        env_ignore_empty=True,
    )

    # --- persistence -------------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./messaging.db"
    database_echo: bool = False

    # --- internal auth (shared FF_INTERNAL_TOKEN wins over FF_MESSAGING_INTERNAL_TOKEN) -------
    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_MESSAGING_INTERNAL_TOKEN"),
    )

    # --- content limits ------------------------------------------------------------------------
    max_text_length: int = Field(default=4000, ge=1, le=20_000)
    max_title_length: int = Field(default=200, ge=1, le=255)
    preview_length: int = Field(default=120, ge=16, le=500)
    max_participants: int = Field(default=10, ge=2, le=100)
    max_body_bytes: int = Field(default=64 * 1024, ge=1024)
    max_event_data_bytes: int = Field(default=8 * 1024, ge=256)

    # --- abuse filter --------------------------------------------------------------------------
    abuse_filter_enabled: bool = True
    abuse_action: AbuseAction = AbuseAction.FLAG
    abuse_terms: Annotated[list[str] | None, NoDecode] = None  # replaces the bundled list
    abuse_terms_extra: StrList = Field(default_factory=list)  # appended to the active list

    # --- send rate limit (per user, sliding window) ---------------------------------------------
    send_rate_limit: int = Field(default=20, ge=1)
    send_rate_window_seconds: float = Field(default=10.0, gt=0)

    # --- attachments (files are uploaded elsewhere; messages carry a URL) ------------------------
    attachment_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    attachment_allowed_mime_types: StrList = Field(
        default_factory=lambda: list(DEFAULT_ATTACHMENT_MIME_TYPES)
    )
    attachment_allowed_hosts: StrList = Field(default_factory=list)  # empty = any https host
    attachment_allow_http: bool = False

    # --- platform accounts ---------------------------------------------------------------------
    platform_user_ids: StrList = Field(default_factory=lambda: ["usr_support"])
    support_user_id: str | None = "usr_support"

    # --- pagination ----------------------------------------------------------------------------
    messages_page_size: int = Field(default=30, ge=1)
    messages_page_size_max: int = Field(default=100, ge=1)
    conversations_page_size: int = Field(default=20, ge=1)
    conversations_page_size_max: int = Field(default=100, ge=1)

    # --- realtime ------------------------------------------------------------------------------
    typing_ttl_seconds: int = Field(default=6, ge=1, le=60)
    typing_throttle_seconds: float = Field(default=2.0, ge=0)
    # Dev auth: accept ?user_id= on the WebSocket URL. Default: allowed only while no internal
    # token is configured (i.e. never behind the gateway in production).
    ws_allow_query_user_id: bool | None = None
    ws_queue_size: int = Field(default=256, ge=8)
    ws_max_connections_per_user: int = Field(default=20, ge=1)
    ws_inbound_rate_limit: int = Field(default=30, ge=1)
    ws_inbound_rate_window_seconds: float = Field(default=10.0, gt=0)
    ws_max_frame_chars: int = Field(default=8192, ge=256)

    @field_validator(
        "abuse_terms",
        "abuse_terms_extra",
        "attachment_allowed_mime_types",
        "attachment_allowed_hosts",
        "platform_user_ids",
        mode="before",
    )
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.messages_page_size > self.messages_page_size_max:
            raise ValueError("messages_page_size must be <= messages_page_size_max")
        if self.conversations_page_size > self.conversations_page_size_max:
            raise ValueError("conversations_page_size must be <= conversations_page_size_max")
        for user_id in [*self.platform_user_ids, *filter(None, [self.support_user_id])]:
            if not is_valid_user_id(user_id):
                raise ValueError(f"invalid platform user id: {user_id!r}")
        return self

    @cached_property
    def platform_ids(self) -> frozenset[str]:
        ids = set(self.platform_user_ids)
        if self.support_user_id:
            ids.add(self.support_user_id)
        return frozenset(ids)

    @property
    def internal_token_value(self) -> str | None:
        if self.internal_token is None:
            return None
        return self.internal_token.get_secret_value() or None

    @property
    def query_user_id_allowed(self) -> bool:
        if self.ws_allow_query_user_id is not None:
            return self.ws_allow_query_user_id
        return self.internal_token_value is None

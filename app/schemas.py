"""请求/响应模型（pydantic v2）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Audience = Literal["member_only", "public", "invite_only"]
SessionStatus = Literal["scheduled", "cancelled"]


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    seq_label: str = Field(default="", max_length=40)
    starts_at: datetime
    ends_at: datetime
    venue_name: str = Field(default="", max_length=120)
    capacity: int = Field(ge=1)
    waitlist_capacity: int = Field(default=0, ge=0)
    requires_approval: bool = False
    audience: Audience = "member_only"

    @model_validator(mode="after")
    def _check_time(self) -> "SessionCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    seq_label: str | None = Field(default=None, max_length=40)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue_name: str | None = Field(default=None, max_length=120)
    capacity: int | None = Field(default=None, ge=1)
    waitlist_capacity: int | None = Field(default=None, ge=0)
    requires_approval: bool | None = None
    audience: Audience | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    site_id: str
    course_id: str
    title: str
    seq_label: str
    starts_at: datetime
    ends_at: datetime
    venue_name: str
    capacity: int
    waitlist_capacity: int
    requires_approval: bool
    audience: Audience
    status: SessionStatus
    event_id: str | None
    sync_status: str
    enrolled_count: int = 0
    created_at: datetime
    updated_at: datetime


class SessionListOut(BaseModel):
    items: list[SessionOut]
    total: int
    limit: int
    offset: int


class ErrorOut(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)

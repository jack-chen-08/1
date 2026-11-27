"""请求/响应模型（出参统一由 crm.permissions.scope 组装，确保金额裁剪只走一处）。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from crm.models import STAGES


class OpportunityCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    site_id: uuid.UUID
    owner_id: str | None = Field(default=None, max_length=64)
    expected_first_year_amount_fen: int = Field(default=0, ge=0)
    weighted_amount_fen: int = Field(default=0, ge=0)
    space_requirement: str | None = Field(default=None, max_length=400)
    stage: str = "new"

    @field_validator("stage")
    @classmethod
    def _stage_valid(cls, v: str) -> str:
        if v not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        return v


class OpportunityPatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    owner_id: str | None = Field(default=None, max_length=64)
    expected_first_year_amount_fen: int | None = Field(default=None, ge=0)
    weighted_amount_fen: int | None = Field(default=None, ge=0)
    space_requirement: str | None = Field(default=None, max_length=400)


class StageAdvance(BaseModel):
    to_stage: str
    note: str | None = Field(default=None, max_length=400)

    @field_validator("to_stage")
    @classmethod
    def _stage_valid(cls, v: str) -> str:
        if v not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        return v


class MergeRequest(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID


class DuplicateQuery(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    site_id: uuid.UUID
    space_requirement: str | None = Field(default=None, max_length=400)

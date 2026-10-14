"""Response models matching common.schema.json TrustScore."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TrustFactorOut(BaseModel):
    key: str
    impact: int
    explanation: str
    explanation_ar: str


class DataGapOut(BaseModel):
    key: str
    label: str
    label_ar: str


class TrustScoreOut(BaseModel):
    supplier_id: str
    score: int
    band: str
    factors: list[TrustFactorOut]
    computed_at: datetime
    confidence: int | None = Field(default=None, ge=0, le=100, description="0-100: how much evidence backs the score")
    model_version: str | None = None
    data_gaps: list[DataGapOut] = []
    flags: list[str] = []


class BatchOut(BaseModel):
    items: list[TrustScoreOut]


class HistoryPoint(BaseModel):
    at: datetime
    score: int
    band: str
    confidence: int | None = None
    source: Literal["mock", "snapshot"]


class HistoryOut(BaseModel):
    supplier_id: str
    points: list[HistoryPoint]


ReportType = Literal["fraud", "counterfeit", "non_delivery", "quality", "misrepresentation", "unsafe_product", "other"]


class ReportIn(BaseModel):
    model_config = {"extra": "forbid"}

    type: ReportType
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be blank")
        return v


class ReportOut(BaseModel):
    id: str
    supplier_id: str
    type: ReportType
    text: str
    status: Literal["pending_review", "accepted", "rejected"]
    created_at: datetime
    score_effect: str = "none_until_reviewed"

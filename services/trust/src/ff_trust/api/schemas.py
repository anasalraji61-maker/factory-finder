"""Response models matching common.schema.json TrustScore."""

from datetime import datetime

from pydantic import BaseModel


class TrustFactorOut(BaseModel):
    key: str
    impact: int
    explanation: str
    explanation_ar: str


class TrustScoreOut(BaseModel):
    supplier_id: str
    score: int
    band: str
    factors: list[TrustFactorOut]
    computed_at: datetime
    confidence: float | None = None
    model_version: str | None = None


class BatchOut(BaseModel):
    items: list[TrustScoreOut]

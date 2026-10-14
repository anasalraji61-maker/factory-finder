"""Response models matching common.schema.json TrustScore."""

from datetime import date, datetime
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
    verification_level: Literal["none", "basic", "documented", "audited"] = "none"


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


# ---- verification documents ----
DocTypeLit = Literal[
    "business_license", "company_registry_reference", "bank_reference", "export_license",
    "factory_photos", "iso_certificate", "other_certificate",
]  # fmt: skip
LevelLit = Literal["none", "basic", "documented", "audited"]
DocStatus = Literal["pending", "approved", "rejected", "withdrawn"]


class DocumentIn(BaseModel):
    model_config = {"extra": "forbid"}

    doc_type: DocTypeLit
    issuing_country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2")
    files: list[str] = Field(min_length=1, max_length=10, description="media-service paths (/v1/media/files/<id>.<ext>)")
    number: str | None = Field(default=None, min_length=4, max_length=64, description="licence / registry / account reference; never stored in clear")
    expires_on: date | None = None
    consent: bool = Field(description="supplier consents to the platform reviewing these documents; must be true")

    @field_validator("issuing_country")
    @classmethod
    def _country(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 2 or not v.isascii() or not v.isalpha():
            raise ValueError("issuing_country must be an ISO 3166-1 alpha-2 code")
        return v


class DocumentOut(BaseModel):
    """Owner view. The document number is never returned, only a masked suffix."""

    id: str
    doc_type: DocTypeLit
    issuing_country: str
    files: list[str]
    number_masked: str | None = None
    expires_on: date | None = None
    status: DocStatus
    is_expired: bool = False
    reason: str | None = None
    consent: bool = True
    created_at: datetime
    reviewed_at: datetime | None = None


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    verification_level: LevelLit = "none"


class AdminDocumentOut(DocumentOut):
    supplier_id: str
    reviewed_by: str | None = None
    approved_on: date | None = None
    duplicate_elsewhere: bool = False


class AdminDocumentPage(BaseModel):
    items: list[AdminDocumentOut]
    total: int
    limit: int
    offset: int


class DecisionIn(BaseModel):
    model_config = {"extra": "forbid"}

    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)
    expires_on: date | None = None


class ExpiryIn(BaseModel):
    model_config = {"extra": "forbid"}

    expires_on: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class AuditEntryOut(BaseModel):
    seq: int
    at: datetime
    actor: str
    action: Literal["submit", "approve", "reject", "revoke", "withdraw", "set_expiry"]
    document_id: str
    supplier_id: str
    from_status: str | None = None
    to_status: str | None = None
    reason: str | None = None
    detail: str | None = None


class AuditOut(BaseModel):
    items: list[AuditEntryOut]


class PublicVerificationOut(BaseModel):
    """Public badge view: level and valid document TYPES only (no numbers, files, dates or reasons)."""

    supplier_id: str
    verification_level: LevelLit
    label: str
    label_ar: str
    valid_types: list[DocTypeLit] = []

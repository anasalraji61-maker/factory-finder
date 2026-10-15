"""Supplier verification documents: owner endpoints (X-Supplier-Id), public badge, admin review (X-Admin-Token)."""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request

from ff_trust.adapters.base import AdapterDisabled
from ff_trust.api.errors import ApiError
from ff_trust.api.schemas import (
    AdminDocumentOut,
    AdminDocumentPage,
    AuditEntryOut,
    AuditOut,
    DecisionIn,
    DocumentIn,
    DocumentListOut,
    DocumentOut,
    ExpiryIn,
    PublicVerificationOut,
    ReleaseIn,
    ReleaseOut,
)
from ff_trust.domain.verification import LEVEL_LABELS
from ff_trust.service import TrustService
from ff_trust.verification import (
    SUPPLIER_RE,
    Document,
    VerificationError,
    VerificationRateLimited,
    reviewer_label,
)

router = APIRouter()


def _svc(request: Request) -> TrustService:
    return request.app.state.service


def supplier_id(x_supplier_id: Annotated[str | None, Header()] = None) -> str:
    """Gateway-verified supplier id (only forwarded for verified claims); never taken from a body or path."""
    v = (x_supplier_id or "").strip()
    if not SUPPLIER_RE.fullmatch(v):
        raise ApiError(401, "supplier_required", "A verified supplier account is required (X-Supplier-Id)")
    return v


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    secret = request.app.state.settings.admin_token
    if not secret:  # disabled unless configured
        raise ApiError(404, "not_found", "Not Found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), secret.encode()):
        raise ApiError(401, "admin_auth_required", "Valid X-Admin-Token required")


Supplier = Annotated[str, Depends(supplier_id)]


def _fail(e: VerificationError) -> ApiError:
    headers = {"Retry-After": str(e.retry_after)} if isinstance(e, VerificationRateLimited) else None
    return ApiError(e.status, e.code, e.message, e.details, headers)


def _out(request: Request, d: Document) -> dict:
    return dict(
        id=d.id, doc_type=d.doc_type, issuing_country=d.issuing_country, files=list(d.files), number_masked=d.number_masked,
        expires_on=d.expires_on, status=d.status, reason=d.reason, consent=d.consent, created_at=d.created_at, reviewed_at=d.reviewed_at,
        is_expired=_svc(request).verification.is_expired(d, request.app.state.service.cfg.doc_default_validity_days),
    )  # fmt: skip


def _admin_out(request: Request, d: Document, duplicate: bool) -> AdminDocumentOut:
    return AdminDocumentOut(**_out(request, d), supplier_id=d.supplier_id, reviewed_by=d.reviewed_by, approved_on=d.approved_on, duplicate_elsewhere=duplicate, released_at=d.released_at)


async def _level(svc: TrustService, sid: str) -> str:
    try:
        r = await svc.for_supplier(sid)
    except AdapterDisabled:
        return "none"
    return r.verification_level if r else "none"


# ---------------- owner ----------------
@router.post("/v1/trust/verification/documents", response_model=DocumentOut, status_code=201)
async def submit_document(body: DocumentIn, request: Request, sid: Supplier) -> DocumentOut:
    try:
        d = await _svc(request).verification.submit(sid, body.doc_type, body.issuing_country, body.files, body.number, body.expires_on, body.consent)
    except VerificationError as e:
        raise _fail(e) from e
    return DocumentOut(**_out(request, d))


@router.get("/v1/trust/verification/documents", response_model=DocumentListOut)
async def my_documents(request: Request, sid: Supplier) -> DocumentListOut:
    svc = _svc(request)
    return DocumentListOut(items=[DocumentOut(**_out(request, d)) for d in await svc.verification.list_for_supplier(sid)], verification_level=await _level(svc, sid))  # type: ignore[arg-type]


@router.delete("/v1/trust/verification/documents/{document_id}", response_model=DocumentOut)
async def withdraw_document(document_id: str, request: Request, sid: Supplier) -> DocumentOut:
    svc = _svc(request)
    try:
        d = await svc.verification.withdraw(sid, document_id)
    except VerificationError as e:
        raise _fail(e) from e
    svc.invalidate(sid)
    return DocumentOut(**_out(request, d))


# ---------------- public badge ----------------
@router.get("/v1/trust/suppliers/{supplier_id}/verification", response_model=PublicVerificationOut)
async def public_verification(supplier_id: str, request: Request) -> PublicVerificationOut:
    svc = _svc(request)
    try:
        r = await svc.for_supplier(supplier_id)
    except AdapterDisabled as e:
        raise ApiError(503, "adapter_disabled", str(e)) from e
    if r is None:
        raise ApiError(404, "supplier_not_found", f"No trust data for {supplier_id}")
    ev = await svc.verification.evidence_for(supplier_id)
    types: list[str] = []
    if ev is not None and r.verification_level != "none":
        from ff_trust.domain.verification import valid_docs

        types = sorted({d.doc_type for d in valid_docs(ev, svc.verification.today(), svc.cfg.doc_default_validity_days)})
    en, ar = LEVEL_LABELS[r.verification_level]
    return PublicVerificationOut(supplier_id=supplier_id, verification_level=r.verification_level, label=en, label_ar=ar, valid_types=types)  # type: ignore[arg-type]


# ---------------- admin ----------------
admin = APIRouter(prefix="/v1/admin/trust/verification", dependencies=[Depends(require_admin)])


@admin.get("/documents", response_model=AdminDocumentPage)
async def admin_list(
    request: Request, status: Literal["pending", "approved", "rejected", "withdrawn", "all"] = "pending",
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100000),
) -> AdminDocumentPage:  # fmt: skip
    st = _svc(request).verification
    rows, total = await st.list_by_status(None if status == "all" else status, limit, offset)
    dups = await st.duplicate_flags(rows)
    return AdminDocumentPage(items=[_admin_out(request, d, d.id in dups) for d in rows], total=total, limit=limit, offset=offset)


@admin.post("/documents/{document_id}/decision", response_model=AdminDocumentOut)
async def admin_decide(
    document_id: str, body: DecisionIn, request: Request, x_reviewer: Annotated[str | None, Header()] = None
) -> AdminDocumentOut:
    svc = _svc(request)
    try:
        d = await svc.verification.decide(document_id, body.decision, body.reason, reviewer_label(x_reviewer), body.expires_on)
    except VerificationError as e:
        raise _fail(e) from e
    svc.invalidate(d.supplier_id)  # the score and badge change on the next read
    return _admin_out(request, d, await svc.verification.duplicate_elsewhere(d))


@admin.put("/documents/{document_id}/expiry", response_model=AdminDocumentOut)
async def admin_expiry(
    document_id: str, body: ExpiryIn, request: Request, x_reviewer: Annotated[str | None, Header()] = None
) -> AdminDocumentOut:
    svc = _svc(request)
    try:
        d = await svc.verification.set_expiry(document_id, body.expires_on, body.reason, reviewer_label(x_reviewer))
    except VerificationError as e:
        raise _fail(e) from e
    svc.invalidate(d.supplier_id)
    return _admin_out(request, d, await svc.verification.duplicate_elsewhere(d))


@admin.post("/suppliers/{supplier_id}/release", response_model=ReleaseOut)
async def admin_release_supplier(
    supplier_id: str, request: Request, body: ReleaseIn | None = None, x_reviewer: Annotated[str | None, Header()] = None
) -> ReleaseOut:
    """Claim released/revoked (gateway): withdraw live documents and hide all of them from the next claimant. Idempotent."""
    svc = _svc(request)
    if not SUPPLIER_RE.fullmatch(supplier_id):
        raise ApiError(422, "invalid_supplier_id", "Invalid supplier id")
    n, w = await svc.verification.release_supplier(supplier_id, reviewer_label(x_reviewer), body.reason if body else None)
    svc.invalidate(supplier_id)
    return ReleaseOut(supplier_id=supplier_id, released_documents=n, withdrawn_documents=w, verification_level=await _level(svc, supplier_id))  # type: ignore[arg-type]


@admin.get("/audit", response_model=AuditOut)
async def admin_audit(request: Request, document_id: str | None = Query(None, max_length=64), supplier_id: str | None = Query(None, max_length=128), limit: int = Query(100, ge=1, le=500)) -> AuditOut:
    rows = await _svc(request).verification.audit.list(document_id, supplier_id, limit)
    return AuditOut(items=[AuditEntryOut(**{k: getattr(e, k) for k in AuditEntryOut.model_fields}) for e in rows])


router.include_router(admin)

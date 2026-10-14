"""Supplier verification documents: store, state machine, append-only audit log, media-path validation.

Process-local like the other stores (this service has no database; DDL for a future table lives in
`migrations/`). Raw document numbers are NEVER stored: only an HMAC fingerprint (duplicate detection) and a masked
suffix. Everything is bounded.

States: pending -> approved | rejected | withdrawn;  approved -> rejected (revoke, reason required) | withdrawn.
rejected / withdrawn are terminal. "expired" is derived (effective expiry < today), never stored.
"""

import hashlib
import hmac
import re
import secrets
import threading
import unicodedata
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from ff_trust.domain.verification import (
    DOC_TYPES,
    NUMBERED,
    VerificationEvidence,
    VerifiedDoc,
    effective_expiry,
)

STATUSES = ("pending", "approved", "rejected", "withdrawn")
ACTIVE = ("pending", "approved")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("approved", "rejected", "withdrawn"),
    "approved": ("rejected", "withdrawn"),
    "rejected": (),
    "withdrawn": (),
}
SUPPLIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MEDIA_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}\.[A-Za-z0-9]{2,8}$")
_REVIEWER_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


class VerificationError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


class VerificationRateLimited(VerificationError):
    def __init__(self, retry_after: int):
        super().__init__(429, "rate_limited", "Too many document submissions; try again later", {"retry_after_seconds": retry_after})
        self.retry_after = retry_after


def _now() -> datetime:
    return datetime.now(UTC)


def clean_reason(text: str | None) -> str | None:
    if text is None:
        return None
    t = "".join(" " if ch.isspace() else ch for ch in text if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf"))
    return " ".join(t.split()) or None


def reviewer_label(raw: str | None) -> str:
    v = (raw or "").strip()
    return f"admin:{v}" if _REVIEWER_RE.fullmatch(v) else "admin"


def normalise_number(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def mask_number(norm: str) -> str:
    """Show at most the last 4 characters, and only when the number is long enough to stay ambiguous."""
    return "****" + norm[-4:] if len(norm) >= 8 else "****"


@dataclass(frozen=True, slots=True)
class MediaRules:
    path_prefixes: tuple[str, ...] = ("/v1/media/files/",)
    allowed_hosts: tuple[str, ...] = ()
    allow_http: bool = False
    max_files: int = 10
    max_url_length: int = 2048


def check_media(urls: list[str], rules: MediaRules) -> tuple[str, ...]:
    """Media-service references only (path prefix + file-name shape); no query, fragment or credentials."""
    err = VerificationError(422, "file_url_not_allowed", "Files must be media-service uploads")
    if not 1 <= len(urls) <= rules.max_files:
        raise VerificationError(422, "invalid_files", f"Provide 1 to {rules.max_files} files", {"max": rules.max_files})
    out: list[str] = []
    schemes = {"https", "http"} if rules.allow_http else {"https"}
    for raw in urls:
        url = raw.strip()
        if not url or len(url) > rules.max_url_length or any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in url):
            raise err
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").rstrip(".").lower()
            creds = parts.username is not None or parts.password is not None
        except ValueError as exc:
            raise err from exc
        if parts.query or parts.fragment or creds:
            raise err
        if (parts.scheme or parts.netloc) and (parts.scheme.lower() not in schemes or not host or host not in rules.allowed_hosts):
            raise err
        prefix = next((p for p in rules.path_prefixes if parts.path.startswith(p)), None)
        if prefix is None or not _MEDIA_FILE_RE.fullmatch(parts.path[len(prefix):]):
            raise err
        if url not in out:
            out.append(url)
    return tuple(out)


@dataclass(slots=True)
class Document:
    id: str
    supplier_id: str
    doc_type: str
    issuing_country: str
    files: tuple[str, ...]
    number_masked: str | None
    number_fingerprint: str | None  # internal only, never serialised
    expires_on: date | None
    consent: bool
    created_at: datetime
    status: str = "pending"
    reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    approved_on: date | None = None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    at: datetime
    actor: str  # "supplier:<id>" | "admin[:label]"
    action: str  # submit | approve | reject | revoke | withdraw | set_expiry
    document_id: str
    supplier_id: str
    from_status: str | None
    to_status: str | None
    reason: str | None = None
    detail: str | None = None  # e.g. "expires_on: 2027-01-01 -> 2028-01-01"


@dataclass
class AuditLog:
    """Append-only: exposes `append` and read access only (entries are frozen). Oldest dropped past `max_entries`."""

    max_entries: int = 200_000
    _entries: deque[AuditEntry] = field(default_factory=deque)
    _seq: int = 0

    def append(self, clock: Callable[[], datetime], **kw) -> AuditEntry:
        self._seq += 1
        e = AuditEntry(seq=self._seq, at=clock(), **kw)
        self._entries.append(e)
        while len(self._entries) > self.max_entries:
            self._entries.popleft()
        return e

    def list(self, document_id: str | None = None, supplier_id: str | None = None, limit: int = 100) -> list[AuditEntry]:
        rows = [e for e in self._entries if (document_id is None or e.document_id == document_id) and (supplier_id is None or e.supplier_id == supplier_id)]
        return rows[-limit:][::-1]  # newest first

    def __len__(self) -> int:
        return len(self._entries)


class VerificationStore:
    def __init__(
        self, rules: MediaRules | None = None, *, rate_limit: int = 10, rate_window: int = 3600, max_per_supplier: int = 30,
        max_per_type: int = 5, max_total: int = 20000, hash_key: str | None = None, max_suppliers: int = 10000,
        clock: Callable[[], datetime] = _now,
    ):  # fmt: skip
        self.rules = rules or MediaRules()
        self.rate_limit, self.rate_window = rate_limit, rate_window
        self.max_per_supplier, self.max_per_type, self.max_total = max_per_supplier, max_per_type, max_total
        self.max_suppliers = max_suppliers
        self._key = (hash_key or secrets.token_hex(32)).encode()
        self.clock = clock
        self.audit = AuditLog()
        self._docs: dict[str, Document] = {}
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.RLock()

    def today(self) -> date:
        return self.clock().date()

    def _fingerprint(self, doc_type: str, country: str, norm: str) -> str:
        return hmac.new(self._key, f"{doc_type}|{country}|{norm}".encode(), hashlib.sha256).hexdigest()

    # ---- supplier side ----
    def submit(self, supplier_id: str, doc_type: str, issuing_country: str, files: list[str], number: str | None, expires_on: date | None, consent: bool) -> Document:
        if doc_type not in DOC_TYPES:
            raise VerificationError(422, "invalid_doc_type", "Unknown document type", {"allowed": list(DOC_TYPES)})
        if consent is not True:
            raise VerificationError(422, "consent_required", "Explicit consent to review these documents is required")
        today = self.today()
        if expires_on is not None and expires_on < today:
            raise VerificationError(422, "already_expired", "Document is already expired")
        norm = normalise_number(number) if number else ""
        if doc_type in NUMBERED and not norm:
            raise VerificationError(422, "number_required", "A document number or reference is required for this type")
        if doc_type not in NUMBERED and norm:
            raise VerificationError(422, "number_not_allowed", "This document type carries no number")
        paths = check_media(files, self.rules)
        with self._lock:
            now = self.clock()
            self._rate_check(supplier_id, now)
            mine = [d for d in self._docs.values() if d.supplier_id == supplier_id and d.status in ACTIVE]
            if len(mine) >= self.max_per_supplier:
                raise VerificationError(409, "document_limit_reached", "Too many active documents", {"max": self.max_per_supplier})
            if sum(1 for d in mine if d.doc_type == doc_type) >= self.max_per_type:
                raise VerificationError(409, "document_type_limit_reached", "Too many active documents of this type", {"max": self.max_per_type})
            fp = self._fingerprint(doc_type, issuing_country, norm) if norm else None
            if fp and any(d.number_fingerprint == fp for d in mine):
                raise VerificationError(409, "duplicate_document", "This document was already submitted")
            if len(self._docs) >= self.max_total:
                self._evict_one()
            self._hits[supplier_id].append(now)
            doc = Document(uuid.uuid4().hex, supplier_id, doc_type, issuing_country, paths, mask_number(norm) if norm else None, fp, expires_on, True, now)
            self._docs[doc.id] = doc
            self.audit.append(self.clock, actor=f"supplier:{supplier_id}", action="submit", document_id=doc.id, supplier_id=supplier_id, from_status=None, to_status="pending")
            return doc

    def _rate_check(self, supplier_id: str, now: datetime) -> None:
        if supplier_id not in self._hits and len(self._hits) >= self.max_suppliers:
            for sid in [s for s, h in self._hits.items() if not h or (now - h[-1]).total_seconds() >= self.rate_window]:
                del self._hits[sid]
            if len(self._hits) >= self.max_suppliers:
                del self._hits[next(iter(self._hits))]
        hits = self._hits[supplier_id]
        while hits and (now - hits[0]).total_seconds() >= self.rate_window:
            hits.popleft()
        if len(hits) >= self.rate_limit:
            raise VerificationRateLimited(max(1, int(self.rate_window - (now - hits[0]).total_seconds())))

    def _evict_one(self) -> None:
        for did, d in self._docs.items():  # oldest closed document first; never drop live evidence
            if d.status in ("rejected", "withdrawn"):
                del self._docs[did]
                return
        raise VerificationError(503, "capacity_reached", "Verification store is full; try later")

    def list_for_supplier(self, supplier_id: str) -> list[Document]:
        with self._lock:
            return sorted((d for d in self._docs.values() if d.supplier_id == supplier_id), key=lambda d: d.created_at)

    def withdraw(self, supplier_id: str, doc_id: str) -> Document:
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None or d.supplier_id != supplier_id:  # other suppliers' documents look nonexistent
                raise VerificationError(404, "document_not_found", "Document not found")
            return self._move(d, "withdrawn", f"supplier:{supplier_id}", "withdraw", None)

    # ---- admin side ----
    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def list_by_status(self, status: str | None, limit: int, offset: int) -> tuple[list[Document], int]:
        with self._lock:
            rows = sorted((d for d in self._docs.values() if status is None or d.status == status), key=lambda d: d.created_at)
            return rows[offset: offset + limit], len(rows)

    def duplicate_elsewhere(self, d: Document) -> bool:
        """True when another supplier holds an active document with the same type+country+number fingerprint."""
        if not d.number_fingerprint:
            return False
        return any(o.number_fingerprint == d.number_fingerprint and o.supplier_id != d.supplier_id and o.status in ACTIVE for o in self._docs.values())

    def _move(self, d: Document, to: str, actor: str, action: str, reason: str | None) -> Document:
        if to not in TRANSITIONS[d.status]:
            raise VerificationError(409, "invalid_transition", f"Cannot move a {d.status} document to {to}", {"from": d.status, "to": to})
        frm = d.status
        now = self.clock()
        d.status = to
        if to != "withdrawn" or actor.startswith("admin"):
            d.reviewed_by, d.reviewed_at = actor, now
        if reason is not None:
            d.reason = reason
        if to == "approved":
            d.approved_on = now.date()
        self.audit.append(self.clock, actor=actor, action=action, document_id=d.id, supplier_id=d.supplier_id, from_status=frm, to_status=to, reason=reason)
        return d

    def decide(self, doc_id: str, decision: str, reason: str | None, reviewer: str, expires_on: date | None = None) -> Document:
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None:
                raise VerificationError(404, "document_not_found", "Document not found")
            reason = clean_reason(reason)
            if decision == "approve":
                exp = expires_on or d.expires_on
                if exp is not None and exp < self.today():
                    raise VerificationError(422, "already_expired", "Cannot approve an expired document")
                if d.status != "pending":
                    raise VerificationError(409, "invalid_transition", f"Cannot move a {d.status} document to approved", {"from": d.status, "to": "approved"})
                if expires_on is not None:
                    d.expires_on = expires_on
                return self._move(d, "approved", reviewer, "approve", reason)
            if not reason:
                raise VerificationError(422, "reason_required", "A reason is required to reject or revoke")
            action = "revoke" if d.status == "approved" else "reject"
            return self._move(d, "rejected", reviewer, action, reason)

    def set_expiry(self, doc_id: str, expires_on: date | None, reason: str | None, reviewer: str) -> Document:
        with self._lock:
            d = self._docs.get(doc_id)
            if d is None:
                raise VerificationError(404, "document_not_found", "Document not found")
            if d.status not in ACTIVE:
                raise VerificationError(409, "invalid_transition", f"Cannot change expiry of a {d.status} document", {"from": d.status})
            if expires_on is not None and expires_on < self.today():
                raise VerificationError(422, "already_expired", "Expiry date is in the past")
            old = d.expires_on
            d.expires_on = expires_on
            self.audit.append(self.clock, actor=reviewer, action="set_expiry", document_id=d.id, supplier_id=d.supplier_id, from_status=d.status, to_status=d.status, reason=clean_reason(reason), detail=f"expires_on: {old} -> {expires_on}")
            return d

    # ---- scoring ----
    def evidence_for(self, supplier_id: str) -> VerificationEvidence | None:
        with self._lock:
            docs = [VerifiedDoc(doc_type=d.doc_type, approved_on=d.approved_on or d.created_at.date(), expires_on=d.expires_on) for d in self._docs.values() if d.supplier_id == supplier_id and d.status == "approved"]  # type: ignore[arg-type]
        return VerificationEvidence(documents=docs) if docs else None

    def is_expired(self, d: Document, default_validity_days: int) -> bool:
        if d.status != "approved" or d.approved_on is None:
            return False
        return effective_expiry(VerifiedDoc(doc_type=d.doc_type, approved_on=d.approved_on, expires_on=d.expires_on), default_validity_days) < self.today()  # type: ignore[arg-type]


__all__ = ["Document", "AuditEntry", "VerificationStore", "VerificationError", "MediaRules"]

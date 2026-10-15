"""Supplier verification documents: DB-backed store, state machine, append-only audit log, media-path validation.

Persistence: SQLAlchemy async (see ``ff_trust.db``). Raw document numbers are NEVER stored: only a keyed (HMAC)
fingerprint for duplicate detection and a masked suffix. Every state change is one transaction that does a
conditional ``UPDATE ... WHERE status = <expected>`` (row-level check, no double-approve race) and appends the audit row.

States: pending -> approved | rejected | withdrawn;  approved -> rejected (revoke, reason required) | withdrawn.
rejected / withdrawn are terminal. "expired" is derived (effective expiry < today), never stored.
"""

import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ff_trust.db import Database, trust_meta, verification_audit, verification_documents
from ff_trust.domain.verification import (
    DOC_TYPES,
    NUMBERED,
    VerificationEvidence,
    VerifiedDoc,
    effective_expiry,
)

log = logging.getLogger("ff_trust.verification")

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
    path_prefixes: tuple[str, ...] = ("/v1/media/private/",)
    allowed_hosts: tuple[str, ...] = ()
    allow_http: bool = False
    max_files: int = 10
    max_url_length: int = 2048


def _file_key(path: str) -> str:
    """Media file id without directory or extension (same upload under any prefix/extension is the same file)."""
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()


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


_D = verification_documents
_A = verification_audit


def _doc(row) -> Document:
    m = row._mapping
    return Document(
        id=m["id"], supplier_id=m["supplier_id"], doc_type=m["doc_type"], issuing_country=m["issuing_country"],
        files=tuple(m["files"]), number_masked=m["number_masked"], number_fingerprint=m["number_fingerprint"],
        expires_on=m["expires_on"], consent=bool(m["consent"]), created_at=m["created_at"], status=m["status"],
        reason=m["reason"], reviewed_by=m["reviewed_by"], reviewed_at=m["reviewed_at"], approved_on=m["approved_on"],
    )  # fmt: skip


class AuditLog:
    """Append-only: the only write path is the private in-transaction ``_append`` used by the store (there is no
    update / delete / clear API, and the table has database triggers that reject UPDATE and DELETE)."""

    def __init__(self, db: Database, clock: Callable[[], datetime]):
        self._db, self._clock = db, clock

    @staticmethod
    async def _append(conn, at: datetime, **kw) -> None:
        await conn.execute(insert(_A).values(at=at, **kw))

    async def list(self, document_id: str | None = None, supplier_id: str | None = None, limit: int = 100) -> list[AuditEntry]:
        q = select(_A).order_by(_A.c.seq.desc()).limit(limit)  # newest first
        if document_id is not None:
            q = q.where(_A.c.document_id == document_id)
        if supplier_id is not None:
            q = q.where(_A.c.supplier_id == supplier_id)
        async with self._db.begin() as conn:
            rows = (await conn.execute(q)).all()
        return [AuditEntry(**{k: r._mapping[k] for k in AuditEntry.__dataclass_fields__}) for r in rows]

    async def count(self) -> int:
        async with self._db.begin() as conn:
            return (await conn.execute(select(func.count()).select_from(_A))).scalar_one()


class VerificationStore:
    def __init__(
        self, rules: MediaRules | None = None, *, db: Database | None = None, rate_limit: int = 10, rate_window: int = 3600,
        max_per_supplier: int = 30, max_per_type: int = 5, max_total: int = 20000, hash_key: str | None = None,
        clock: Callable[[], datetime] = _now,
    ):  # fmt: skip
        self.db = db or Database("sqlite+aiosqlite:///:memory:", True)
        self.rules = rules or MediaRules()
        self.rate_limit, self.rate_window = rate_limit, rate_window
        self.max_per_supplier, self.max_per_type, self.max_total = max_per_supplier, max_per_type, max_total
        self._cfg_key = hash_key or None
        self._key: bytes | None = self._cfg_key.encode() if self._cfg_key else None
        self.clock = clock
        self.audit = AuditLog(self.db, clock)

    def today(self) -> date:
        return self.clock().date()

    # ---- keyed fingerprints ----
    async def _hmac_key(self) -> bytes:
        """Configured key, else (dev only) a random key persisted in ``trust_meta`` so restarts keep working."""
        if self._key is None:
            async with self.db.begin() as conn:
                val = (await conn.execute(select(trust_meta.c.value).where(trust_meta.c.key == "dev_hash_key"))).scalar()
                if val is None:
                    val = secrets.token_hex(32)
                    await conn.execute(insert(trust_meta).values(key="dev_hash_key", value=val))
            self._key = val.encode()
        return self._key

    @staticmethod
    def key_check(key: bytes) -> str:
        return hmac.new(key, b"ff-trust-key-check", hashlib.sha256).hexdigest()[:16]

    async def verify_key(self, *, strict: bool) -> None:
        """Startup check: the key must be the one that produced the stored fingerprints (else duplicates go undetected)."""
        check = self.key_check(await self._hmac_key())
        async with self.db.begin() as conn:
            old = (await conn.execute(select(trust_meta.c.value).where(trust_meta.c.key == "hash_key_check"))).scalar()
            if old is None:
                await conn.execute(insert(trust_meta).values(key="hash_key_check", value=check))
                return
        if old != check:
            msg = "FF_TRUST_VERIFICATION_HASH_KEY differs from the key that produced the stored document fingerprints"
            if strict:
                raise RuntimeError(msg + " (refusing to start)")
            log.warning(msg)

    def _fingerprint(self, key: bytes, doc_type: str, country: str, norm: str) -> str:
        return hmac.new(key, f"{doc_type}|{country}|{norm}".encode(), hashlib.sha256).hexdigest()

    # ---- supplier side ----
    async def submit(self, supplier_id: str, doc_type: str, issuing_country: str, files: list[str], number: str | None, expires_on: date | None, consent: bool) -> Document:
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
        fp = self._fingerprint(await self._hmac_key(), doc_type, issuing_country, norm) if norm else None
        try:
            async with self.db.begin() as conn:
                await self.db.lock(conn, f"verification:{supplier_id}")
                now = self.clock()
                await self._rate_check(conn, supplier_id, now)
                mine = (await conn.execute(select(_D.c.doc_type, _D.c.number_fingerprint).where(_D.c.supplier_id == supplier_id, _D.c.status.in_(ACTIVE)))).all()
                if len(mine) >= self.max_per_supplier:
                    raise VerificationError(409, "document_limit_reached", "Too many active documents", {"max": self.max_per_supplier})
                if sum(1 for r in mine if r.doc_type == doc_type) >= self.max_per_type:
                    raise VerificationError(409, "document_type_limit_reached", "Too many active documents of this type", {"max": self.max_per_type})
                if fp and any(r.number_fingerprint == fp for r in mine):
                    raise VerificationError(409, "duplicate_document", "This document was already submitted")
                # ownership link (security-review-2026-10-d item 1): trust cannot ask media who uploaded a file, but a file
                # already attached to ANOTHER supplier's document can never be claimed by a second supplier
                taken = {_file_key(p) for (fl,) in (await conn.execute(select(_D.c.files).where(_D.c.supplier_id != supplier_id))).all() for p in fl}
                if any(_file_key(p) in taken for p in paths):
                    raise VerificationError(409, "file_in_use", "This file is already attached to another supplier's document")
                total = (await conn.execute(select(func.count()).select_from(_D))).scalar_one()
                if total >= self.max_total:
                    await self._evict_one(conn)
                doc = Document(uuid.uuid4().hex, supplier_id, doc_type, issuing_country, paths, mask_number(norm) if norm else None, fp, expires_on, True, now)
                await conn.execute(insert(_D).values(
                    id=doc.id, supplier_id=supplier_id, doc_type=doc_type, issuing_country=issuing_country, files=list(paths),
                    number_masked=doc.number_masked, number_fingerprint=fp, expires_on=expires_on, consent=True, status="pending", created_at=now,
                ))  # fmt: skip
                await AuditLog._append(conn, now, actor=f"supplier:{supplier_id}", action="submit", document_id=doc.id, supplier_id=supplier_id, from_status=None, to_status="pending")
                return doc
        except IntegrityError as exc:  # unique live-fingerprint index: a concurrent identical submission won the race
            raise VerificationError(409, "duplicate_document", "This document was already submitted") from exc

    async def _rate_check(self, conn, supplier_id: str, now: datetime) -> None:
        """Submissions per supplier in the sliding window, counted from the (append-only, never evicted) audit log."""
        cutoff = now - timedelta(seconds=self.rate_window)
        n, first = (await conn.execute(select(func.count(), func.min(_A.c.at)).where(_A.c.supplier_id == supplier_id, _A.c.action == "submit", _A.c.at > cutoff))).one()
        if n >= self.rate_limit:
            raise VerificationRateLimited(max(1, int(self.rate_window - (now - first).total_seconds())))

    async def _evict_one(self, conn) -> None:
        oldest = (await conn.execute(select(_D.c.id).where(_D.c.status.in_(("rejected", "withdrawn"))).order_by(_D.c.created_at).limit(1))).scalar()
        if oldest is None:  # never drop live evidence
            raise VerificationError(503, "capacity_reached", "Verification store is full; try later")
        await conn.execute(delete(_D).where(_D.c.id == oldest))

    async def list_for_supplier(self, supplier_id: str) -> list[Document]:
        async with self.db.begin() as conn:
            rows = (await conn.execute(select(_D).where(_D.c.supplier_id == supplier_id).order_by(_D.c.created_at, _D.c.id))).all()
        return [_doc(r) for r in rows]

    async def withdraw(self, supplier_id: str, doc_id: str) -> Document:
        async with self.db.begin() as conn:
            d = await self._load(conn, doc_id)
            if d is None or d.supplier_id != supplier_id:  # other suppliers' documents look nonexistent
                raise VerificationError(404, "document_not_found", "Document not found")
            return await self._move(conn, d, "withdrawn", f"supplier:{supplier_id}", "withdraw", None)

    # ---- admin side ----
    @staticmethod
    async def _load(conn, doc_id: str) -> Document | None:
        row = (await conn.execute(select(_D).where(_D.c.id == doc_id))).first()
        return _doc(row) if row else None

    async def get(self, doc_id: str) -> Document | None:
        async with self.db.begin() as conn:
            return await self._load(conn, doc_id)

    async def list_by_status(self, status: str | None, limit: int, offset: int) -> tuple[list[Document], int]:
        cond = [] if status is None else [_D.c.status == status]
        async with self.db.begin() as conn:
            total = (await conn.execute(select(func.count()).select_from(_D).where(*cond))).scalar_one()
            rows = (await conn.execute(select(_D).where(*cond).order_by(_D.c.created_at, _D.c.id).limit(limit).offset(offset))).all()
        return [_doc(r) for r in rows], total

    async def duplicate_flags(self, docs: list[Document]) -> set[str]:
        """Ids of documents whose type+country+number fingerprint is also held, active, by another supplier."""
        fps = {d.number_fingerprint for d in docs if d.number_fingerprint}
        if not fps:
            return set()
        async with self.db.begin() as conn:
            rows = (await conn.execute(select(_D.c.number_fingerprint, _D.c.supplier_id).where(_D.c.number_fingerprint.in_(fps), _D.c.status.in_(ACTIVE)))).all()
        holders: dict[str, set[str]] = {}
        for fp, sid in rows:
            holders.setdefault(fp, set()).add(sid)
        return {d.id for d in docs if d.number_fingerprint and (holders.get(d.number_fingerprint, set()) - {d.supplier_id})}

    async def duplicate_elsewhere(self, d: Document) -> bool:
        return d.id in await self.duplicate_flags([d])

    async def _move(self, conn, d: Document, to: str, actor: str, action: str, reason: str | None, **extra) -> Document:
        """One state transition: conditional UPDATE on the status we read (row-level check) + audit row, same transaction."""
        if to not in TRANSITIONS[d.status]:
            raise VerificationError(409, "invalid_transition", f"Cannot move a {d.status} document to {to}", {"from": d.status, "to": to})
        now = self.clock()
        vals: dict = {"status": to, **extra}
        if to != "withdrawn" or actor.startswith("admin"):
            vals["reviewed_by"], vals["reviewed_at"] = actor, now
        if reason is not None:
            vals["reason"] = reason
        if to == "approved":
            vals["approved_on"] = now.date()
        res = await conn.execute(update(_D).where(_D.c.id == d.id, _D.c.status == d.status).values(**vals))
        if res.rowcount != 1:  # somebody else moved it first
            cur = (await conn.execute(select(_D.c.status).where(_D.c.id == d.id))).scalar()
            if cur is None:
                raise VerificationError(404, "document_not_found", "Document not found")
            raise VerificationError(409, "invalid_transition", f"Cannot move a {cur} document to {to}", {"from": cur, "to": to})
        await AuditLog._append(conn, now, actor=actor, action=action, document_id=d.id, supplier_id=d.supplier_id, from_status=d.status, to_status=to, reason=reason)
        return replace(d, **vals)

    async def decide(self, doc_id: str, decision: str, reason: str | None, reviewer: str, expires_on: date | None = None) -> Document:
        async with self.db.begin() as conn:
            d = await self._load(conn, doc_id)
            if d is None:
                raise VerificationError(404, "document_not_found", "Document not found")
            reason = clean_reason(reason)
            if decision == "approve":
                exp = expires_on or d.expires_on
                if exp is not None and exp < self.today():
                    raise VerificationError(422, "already_expired", "Cannot approve an expired document")
                if d.status != "pending":
                    raise VerificationError(409, "invalid_transition", f"Cannot move a {d.status} document to approved", {"from": d.status, "to": "approved"})
                extra = {"expires_on": expires_on} if expires_on is not None else {}
                return await self._move(conn, d, "approved", reviewer, "approve", reason, **extra)
            if not reason:
                raise VerificationError(422, "reason_required", "A reason is required to reject or revoke")
            action = "revoke" if d.status == "approved" else "reject"
            return await self._move(conn, d, "rejected", reviewer, action, reason)

    async def set_expiry(self, doc_id: str, expires_on: date | None, reason: str | None, reviewer: str) -> Document:
        async with self.db.begin() as conn:
            d = await self._load(conn, doc_id)
            if d is None:
                raise VerificationError(404, "document_not_found", "Document not found")
            if d.status not in ACTIVE:
                raise VerificationError(409, "invalid_transition", f"Cannot change expiry of a {d.status} document", {"from": d.status})
            if expires_on is not None and expires_on < self.today():
                raise VerificationError(422, "already_expired", "Expiry date is in the past")
            res = await conn.execute(update(_D).where(_D.c.id == d.id, _D.c.status == d.status).values(expires_on=expires_on))
            if res.rowcount != 1:
                raise VerificationError(409, "invalid_transition", "Document changed state; retry", {"from": d.status})
            await AuditLog._append(conn, self.clock(), actor=reviewer, action="set_expiry", document_id=d.id, supplier_id=d.supplier_id, from_status=d.status, to_status=d.status, reason=clean_reason(reason), detail=f"expires_on: {d.expires_on} -> {expires_on}")
            return replace(d, expires_on=expires_on)

    # ---- scoring ----
    async def evidence_for(self, supplier_id: str) -> VerificationEvidence | None:
        async with self.db.begin() as conn:
            rows = (await conn.execute(select(_D.c.doc_type, _D.c.approved_on, _D.c.created_at, _D.c.expires_on).where(_D.c.supplier_id == supplier_id, _D.c.status == "approved"))).all()
        docs = [VerifiedDoc(doc_type=r.doc_type, approved_on=r.approved_on or r.created_at.date(), expires_on=r.expires_on) for r in rows]  # type: ignore[arg-type]
        return VerificationEvidence(documents=docs) if docs else None

    def is_expired(self, d: Document, default_validity_days: int) -> bool:
        if d.status != "approved" or d.approved_on is None:
            return False
        return effective_expiry(VerifiedDoc(doc_type=d.doc_type, approved_on=d.approved_on, expires_on=d.expires_on), default_validity_days) < self.today()  # type: ignore[arg-type]


__all__ = ["Document", "AuditEntry", "AuditLog", "VerificationStore", "VerificationError", "MediaRules"]

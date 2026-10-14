-- trust: supplier verification documents + append-only audit log.
-- The trust service currently keeps these in memory (ff_trust/verification.py); this DDL is the persistence
-- schema (PostgreSQL; also valid SQLite) for when the service gets a database. Raw document numbers are
-- never a column: only a masked suffix and an HMAC fingerprint.

CREATE TABLE verification_documents (
    id                 TEXT PRIMARY KEY,
    supplier_id        TEXT NOT NULL,
    doc_type           TEXT NOT NULL CHECK (doc_type IN ('business_license','company_registry_reference','bank_reference','export_license','factory_photos','iso_certificate','other_certificate')),
    issuing_country    TEXT NOT NULL CHECK (length(issuing_country) = 2),
    files              TEXT NOT NULL,              -- JSON array of media-service paths
    number_masked      TEXT,                       -- '****' + last 4 at most
    number_fingerprint TEXT,                       -- HMAC-SHA256 hex, internal only
    expires_on         DATE,
    consent            BOOLEAN NOT NULL CHECK (consent),
    status             TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','withdrawn')),
    reason             TEXT,
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMP,
    approved_on        DATE,
    created_at         TIMESTAMP NOT NULL
);
CREATE INDEX ix_verification_documents_supplier ON verification_documents (supplier_id, status);
CREATE INDEX ix_verification_documents_status ON verification_documents (status, created_at);
CREATE INDEX ix_verification_documents_fingerprint ON verification_documents (number_fingerprint);

CREATE TABLE verification_audit (
    seq         INTEGER PRIMARY KEY,
    at          TIMESTAMP NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('submit','approve','reject','revoke','withdraw','set_expiry')),
    document_id TEXT NOT NULL,
    supplier_id TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    reason      TEXT,
    detail      TEXT
);
CREATE INDEX ix_verification_audit_document ON verification_audit (document_id, seq);
-- append-only: no UPDATE / DELETE grants on verification_audit for the application role.

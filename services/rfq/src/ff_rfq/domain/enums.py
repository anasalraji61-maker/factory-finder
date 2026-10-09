"""Enumerations shared by the domain, the persistence layer and the API."""

from enum import StrEnum


class ListingKind(StrEnum):
    """What is being sourced (common schema ``ListingKind``)."""

    PRODUCT = "product"
    RAW_MATERIAL = "raw_material"
    PRODUCTION_LINE = "production_line"


class ListingCondition(StrEnum):
    """Condition of a sourced listing (common schema ``Condition``)."""

    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"


class RequestCondition(StrEnum):
    """Condition the buyer accepts."""

    NEW = "new"
    USED = "used"
    ANY = "any"


class Visibility(StrEnum):
    """``public`` requests are listed in the marketplace feed; ``private`` ones are link-only."""

    PUBLIC = "public"
    PRIVATE = "private"


class RequestStatus(StrEnum):
    OPEN = "open"
    NEGOTIATING = "negotiating"
    AWARDED = "awarded"
    CLOSED = "closed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OfferStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DealStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    IN_FULFILMENT = "in_fulfilment"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"


class DealRole(StrEnum):
    """The caller's side of an offer or a deal."""

    BUYER = "buyer"
    SUPPLIER = "supplier"


class Incoterm(StrEnum):
    EXW = "EXW"
    FCA = "FCA"
    FOB = "FOB"
    CFR = "CFR"
    CIF = "CIF"
    DAP = "DAP"
    DDP = "DDP"


class TrustBand(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"

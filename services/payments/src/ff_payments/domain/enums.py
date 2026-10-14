from enum import StrEnum


class InvoiceKind(StrEnum):
    COMMISSION = "commission"
    DEAL_PAYMENT = "deal_payment"


class InvoiceStatus(StrEnum):
    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    CONFIRMING = "confirming"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED = "failed"
    REFUNDED = "refunded"


class ListingKind(StrEnum):
    PRODUCT = "product"
    RAW_MATERIAL = "raw_material"
    PRODUCTION_LINE = "production_line"


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"

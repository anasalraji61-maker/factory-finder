"""Deterministic mock signals: any supplier id yields stable pseudo-random signals (sha256)."""

import hashlib
from datetime import date

from ff_trust.domain.signals import CertificationRecord, SupplierSignals

_FAR = date(2030, 12, 31)
_EXPIRED = date(2025, 6, 30)

CURATED: dict[str, SupplierSignals] = {
    "sup_demo_gold": SupplierSignals(
        years_in_business=15, verified=True, third_party_audit=True, transactions_count=2400,
        response_rate=0.98, rating_avg=4.8, reviews_count=900, dispute_rate=0.005,
        certifications=["ISO9001", "CE", "ISO14001"], domain_age_years=14, has_physical_address=True,
        contact_consistency=1.0, sanctions_hit=False, price_vs_market_ratio=1.0, country_risk=0.15,
        business_license_status="verified", storefront_age_years=13, repeat_buyer_rate=0.55,
        response_time_hours=2.0, dispute_rate_recent=0.004, refund_rate=0.01, deals_completed=2300,
        deals_cancelled=40, blocked=False,
        certification_records=[CertificationRecord(name="ISO 9001", expires_on=_FAR), CertificationRecord(name="CE", expires_on=_FAR),
                               CertificationRecord(name="ISO 14001", expires_on=_FAR), CertificationRecord(name="BSCI", expires_on=_FAR)],
    ),
    "sup_demo_avg": SupplierSignals(
        years_in_business=4, verified=True, third_party_audit=False, transactions_count=120,
        response_rate=0.75, rating_avg=4.0, reviews_count=35, dispute_rate=0.03,
        certifications=["ISO9001"], domain_age_years=4, has_physical_address=True,
        contact_consistency=0.7, sanctions_hit=False, price_vs_market_ratio=0.9, country_risk=0.35,
        business_license_status="pending", storefront_age_years=3.5, repeat_buyer_rate=0.2,
        response_time_hours=14.0, dispute_rate_recent=0.04, refund_rate=0.03, deals_completed=110,
        deals_cancelled=20, blocked=False,
        certification_records=[CertificationRecord(name="ISO 9001", expires_on=_FAR)],
    ),
    "sup_demo_scam": SupplierSignals(
        years_in_business=0.3, verified=False, third_party_audit=False, transactions_count=2,
        response_rate=0.3, rating_avg=2.5, reviews_count=3, dispute_rate=0.2, certifications=[],
        domain_age_years=0.2, has_physical_address=False, contact_consistency=0.1,
        sanctions_hit=False, price_vs_market_ratio=0.25, country_risk=0.6,
        business_license_status="unverified", storefront_age_years=0.2, repeat_buyer_rate=0.0,
        response_time_hours=60.0, dispute_rate_recent=0.35, refund_rate=0.25, deals_completed=1,
        deals_cancelled=4, blocked=False, certification_records=[],
    ),
    "sup_demo_sanctioned": SupplierSignals(
        years_in_business=12, verified=True, third_party_audit=True, transactions_count=1500,
        response_rate=0.95, rating_avg=4.6, reviews_count=400, dispute_rate=0.01,
        certifications=["ISO9001", "CE"], domain_age_years=10, has_physical_address=True,
        contact_consistency=0.95, sanctions_hit=True, price_vs_market_ratio=1.0, country_risk=0.5,
        business_license_status="verified", storefront_age_years=9, repeat_buyer_rate=0.5,
        response_time_hours=3.0, dispute_rate_recent=0.01, refund_rate=0.01, deals_completed=1400,
        deals_cancelled=30, blocked=False,
        certification_records=[CertificationRecord(name="ISO 9001", expires_on=_FAR), CertificationRecord(name="CE", expires_on=_FAR)],
    ),
}


def signals_from_hash(supplier_id: str) -> SupplierSignals:
    b = hashlib.sha256(supplier_id.encode()).digest()
    q = b[0] / 255  # latent "quality" 0..1, drives correlated signals
    u = [x / 255 for x in b[1:16]]
    b2 = hashlib.sha256(f"{supplier_id}:v2".encode()).digest()
    w = [x / 255 for x in b2[:12]]  # independent stream: v1 values above are unchanged
    certs = ["ISO9001", "CE", "ISO14001", "RoHS", "UL"][: int(q * 4 + u[0] * 1.5)]
    cert_names = ["ISO9001", "CE", "ISO14001", "RoHS", "UL"][: int(q * 4 + u[0] * 1.5)]
    done = int(q * 800 * (0.4 + w[4]))
    lic = "verified" if w[0] < q * 0.9 + 0.05 else "pending" if w[0] < q * 0.9 + 0.3 else "unverified"
    return SupplierSignals(
        business_license_status=lic,
        certification_records=[
            CertificationRecord(name=c, expires_on=_EXPIRED if w[1] > 0.9 and i == 0 else _FAR)
            for i, c in enumerate(cert_names)
        ],
        storefront_age_years=round(q * 10 + w[2] * 3, 1),
        repeat_buyer_rate=round(min(1.0, 0.05 + q * 0.45 + w[3] * 0.15), 2),
        response_time_hours=round(max(0.5, 48 - q * 44 + w[5] * 8), 1),
        dispute_rate_recent=round(max(0.0, 0.08 * (1 - q) * w[6] * 1.5), 3),
        refund_rate=round(max(0.0, 0.06 * (1 - q) * w[7]), 3),
        deals_completed=done,
        deals_cancelled=int(done * 0.12 * (1 - q) * (0.3 + w[8])),
        blocked=False,
        years_in_business=round(q * 14 + u[1] * 3, 1),
        verified=u[2] < q + 0.15,
        third_party_audit=u[3] < q * 0.8,
        transactions_count=int(q * 1500 * (0.4 + u[4])),
        response_rate=round(min(1.0, 0.4 + q * 0.5 + u[5] * 0.1), 2),
        rating_avg=round(min(5.0, 3.0 + q * 1.6 + u[6] * 0.3), 1),
        reviews_count=int(q * 500 * (0.3 + u[7])),
        dispute_rate=round(max(0.0, 0.08 * (1 - q) * u[8] * 1.5), 3),
        certifications=certs,
        domain_age_years=round(q * 12 + u[9] * 3, 1),
        has_physical_address=u[10] < q + 0.3,
        contact_consistency=round(min(1.0, 0.4 + q * 0.5 + u[11] * 0.1), 2),
        sanctions_hit=False,
        price_vs_market_ratio=round(0.75 + u[12] * 0.5, 2),
        country_risk=round(0.1 + u[13] * 0.5, 2),
    )


def mock_history_offsets(supplier_id: str, months: int) -> list[int]:
    """Deterministic score deltas (relative to the current score) for the last `months` months.

    Oldest first; the walk is bounded and settles towards 0 near the present."""
    b = hashlib.sha256(f"{supplier_id}:history".encode()).digest()
    out = []
    for i in range(months):
        remaining = months - i  # months before the latest mock point
        amp = min(12, remaining + 2)
        out.append(round((b[i % 32] / 255 - 0.5) * 2 * amp * (0.3 + 0.7 * (remaining / months))))
    return out


class MockSignalsAdapter:
    name = "mock"
    has_mock_history = True

    async def get_signals(self, supplier_id: str) -> SupplierSignals | None:
        sig = CURATED.get(supplier_id) or signals_from_hash(supplier_id)
        return sig.model_copy(update={"supplier_id": supplier_id})

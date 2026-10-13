"""Deterministic mock signals: any supplier id yields stable pseudo-random signals (sha256)."""

import hashlib

from ff_trust.domain.signals import SupplierSignals

CURATED: dict[str, SupplierSignals] = {
    "sup_demo_gold": SupplierSignals(
        years_in_business=15, verified=True, third_party_audit=True, transactions_count=2400,
        response_rate=0.98, rating_avg=4.8, reviews_count=900, dispute_rate=0.005,
        certifications=["ISO9001", "CE", "ISO14001"], domain_age_years=14, has_physical_address=True,
        contact_consistency=1.0, sanctions_hit=False, price_vs_market_ratio=1.0, country_risk=0.15,
    ),
    "sup_demo_avg": SupplierSignals(
        years_in_business=4, verified=True, third_party_audit=False, transactions_count=120,
        response_rate=0.75, rating_avg=4.0, reviews_count=35, dispute_rate=0.03,
        certifications=["ISO9001"], domain_age_years=4, has_physical_address=True,
        contact_consistency=0.7, sanctions_hit=False, price_vs_market_ratio=0.9, country_risk=0.35,
    ),
    "sup_demo_scam": SupplierSignals(
        years_in_business=0.3, verified=False, third_party_audit=False, transactions_count=2,
        response_rate=0.3, rating_avg=2.5, reviews_count=3, dispute_rate=0.2, certifications=[],
        domain_age_years=0.2, has_physical_address=False, contact_consistency=0.1,
        sanctions_hit=False, price_vs_market_ratio=0.25, country_risk=0.6,
    ),
    "sup_demo_sanctioned": SupplierSignals(
        years_in_business=12, verified=True, third_party_audit=True, transactions_count=1500,
        response_rate=0.95, rating_avg=4.6, reviews_count=400, dispute_rate=0.01,
        certifications=["ISO9001", "CE"], domain_age_years=10, has_physical_address=True,
        contact_consistency=0.95, sanctions_hit=True, price_vs_market_ratio=1.0, country_risk=0.5,
    ),
}


def signals_from_hash(supplier_id: str) -> SupplierSignals:
    b = hashlib.sha256(supplier_id.encode()).digest()
    q = b[0] / 255  # latent "quality" 0..1, drives correlated signals
    u = [x / 255 for x in b[1:16]]
    certs = ["ISO9001", "CE", "ISO14001", "RoHS", "UL"][: int(q * 4 + u[0] * 1.5)]
    return SupplierSignals(
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


class MockSignalsAdapter:
    name = "mock"

    async def get_signals(self, supplier_id: str) -> SupplierSignals | None:
        sig = CURATED.get(supplier_id) or signals_from_hash(supplier_id)
        return sig.model_copy(update={"supplier_id": supplier_id})

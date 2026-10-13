"""Glue: adapter + engine + cache -> TrustScoreOut."""

from datetime import UTC, datetime

from ff_trust.adapters.base import SignalsAdapter
from ff_trust.api.schemas import TrustFactorOut, TrustScoreOut
from ff_trust.cache import TTLCache
from ff_trust.config import ScoringConfig
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import SupplierSignals


def to_out(supplier_id: str, signals: SupplierSignals, cfg: ScoringConfig) -> TrustScoreOut:
    a = assess(signals, cfg)
    return TrustScoreOut(
        supplier_id=supplier_id, score=a.score, band=a.band.value,
        factors=[TrustFactorOut(key=f.key, impact=f.impact, explanation=f.explanation, explanation_ar=f.explanation_ar) for f in a.factors],
        computed_at=datetime.now(UTC), confidence=a.confidence, model_version=a.model_version,
    )  # fmt: skip


class TrustService:
    def __init__(self, adapter: SignalsAdapter, cfg: ScoringConfig, cache: TTLCache[TrustScoreOut]):
        self.adapter, self.cfg, self.cache = adapter, cfg, cache

    async def for_supplier(self, supplier_id: str) -> TrustScoreOut | None:
        hit = self.cache.get(supplier_id)
        if hit:
            return hit
        signals = await self.adapter.get_signals(supplier_id)
        if signals is None:
            return None
        out = to_out(supplier_id, signals, self.cfg)
        self.cache.set(supplier_id, out)
        return out

    def evaluate(self, signals: SupplierSignals) -> TrustScoreOut:
        return to_out(signals.supplier_id or "adhoc", signals, self.cfg)

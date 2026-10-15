"""Glue: adapter + engine + cache + stores -> TrustScoreOut."""

from datetime import UTC, datetime, timedelta

from ff_trust.adapters.base import SignalsAdapter
from ff_trust.api.schemas import (
    DataGapOut,
    HistoryOut,
    HistoryPoint,
    ReportOut,
    TrustFactorOut,
    TrustScoreOut,
)
from ff_trust.cache import TTLCache
from ff_trust.clients.reviews import ReviewsClient
from ff_trust.config import ScoringConfig
from ff_trust.domain.models import Assessment, TrustBand
from ff_trust.domain.scoring import assess, band_for
from ff_trust.domain.signals import SupplierSignals
from ff_trust.store import Report, ReportStore, Snapshot, SnapshotStore
from ff_trust.verification import VerificationStore


def to_out(supplier_id: str, signals: SupplierSignals, cfg: ScoringConfig) -> TrustScoreOut:
    return _out(supplier_id, assess(signals, cfg))


def _out(supplier_id: str, a: Assessment) -> TrustScoreOut:
    return TrustScoreOut(
        supplier_id=supplier_id, score=a.score, band=a.band.value,
        factors=[TrustFactorOut(key=f.key, impact=f.impact, explanation=f.explanation, explanation_ar=f.explanation_ar) for f in a.factors],
        computed_at=datetime.now(UTC), confidence=a.confidence, model_version=a.model_version,
        data_gaps=[DataGapOut(key=g.key, label=g.label, label_ar=g.label_ar) for g in a.data_gaps], flags=list(a.flags),
        verification_level=a.verification_level,  # type: ignore[arg-type]
    )  # fmt: skip


def report_out(r: Report) -> ReportOut:
    return ReportOut(id=r.id, supplier_id=r.supplier_id, type=r.type, text=r.text, status=r.status, created_at=r.created_at)  # type: ignore[arg-type]


class TrustService:
    def __init__(
        self, adapter: SignalsAdapter, cfg: ScoringConfig, cache: TTLCache[TrustScoreOut],
        snapshots: SnapshotStore | None = None, reports: ReportStore | None = None, history_months: int = 12,
        reviews: ReviewsClient | None = None, verification: VerificationStore | None = None,
    ):  # fmt: skip
        self.adapter, self.cfg, self.cache = adapter, cfg, cache
        self.snapshots = snapshots or SnapshotStore()
        self.reports = reports or ReportStore()
        self.history_months = history_months
        self.reviews = reviews
        self.verification = verification or VerificationStore()

    async def for_supplier(self, supplier_id: str) -> TrustScoreOut | None:
        hit = self.cache.get(supplier_id)
        if hit:
            return hit
        signals = await self.adapter.get_signals(supplier_id)
        if signals is None:
            return None
        if self.reviews is not None and signals.review_summary is None:
            try:  # optional enrichment: any failure leaves the score as it was without it
                summary = await self.reviews.fetch(supplier_id)
            except Exception:  # noqa: BLE001
                summary = None
            if summary is not None:
                signals = signals.model_copy(update={"review_summary": summary})
        accepted = await self.reports.accepted_count(supplier_id)
        if accepted:  # only reviewed (accepted) reports ever touch the score
            signals = signals.model_copy(update={"confirmed_reports": accepted})
        evidence = await self.verification.evidence_for(supplier_id)  # approved documents only; pending/rejected never count
        if evidence is not None and signals.verification is None:
            signals = signals.model_copy(update={"verification": evidence})
        out = to_out(supplier_id, signals, self.cfg)
        self.cache.set(supplier_id, out)
        await self.snapshots.add(supplier_id, Snapshot(out.computed_at, out.score, out.band, out.confidence or 0))
        return out

    def evaluate(self, signals: SupplierSignals) -> TrustScoreOut:
        return to_out(signals.supplier_id or "adhoc", signals, self.cfg)

    async def history(self, supplier_id: str) -> HistoryOut | None:
        """Oldest-first score history: deterministic mock points (mock adapter only) + stored snapshots."""
        cur = await self.for_supplier(supplier_id)
        if cur is None:
            return None
        points: list[HistoryPoint] = []
        if getattr(self.adapter, "has_mock_history", False):
            from ff_trust.adapters.mock import mock_history_offsets

            hard = any(f in ("sanctions_hit", "blocked_flag") for f in cur.flags)
            day = cur.computed_at.replace(hour=0, minute=0, second=0, microsecond=0)
            offs = mock_history_offsets(supplier_id, self.history_months)
            for i, off in enumerate(offs):
                score = max(0, min(100, cur.score + off))
                if hard:
                    score = min(score, self.cfg.sanctions_cap)
                band = "red" if hard else "unknown" if cur.band == "unknown" else band_for(score, self.cfg).value
                points.append(HistoryPoint(at=day - timedelta(days=30 * (self.history_months - i)), score=score, band=band, confidence=cur.confidence, source="mock"))  # fmt: skip
        points += [HistoryPoint(at=s.at, score=s.score, band=s.band, confidence=s.confidence, source="snapshot") for s in await self.snapshots.list(supplier_id)]  # fmt: skip
        points.sort(key=lambda p: p.at)
        return HistoryOut(supplier_id=supplier_id, points=points)

    async def add_report(self, supplier_id: str, user_id: str, rtype: str, text: str, low_trust: bool = False) -> Report:
        return await self.reports.add(supplier_id, user_id, rtype, text, low_trust)

    def invalidate(self, supplier_id: str) -> None:
        self.cache.delete(supplier_id)

    async def review_report(self, report_id: str, status: str) -> Report | None:
        """Moderator hook (not exposed over HTTP). Accepting re-scores the supplier."""
        r = await self.reports.review(report_id, status)
        if r is not None:
            self.cache.delete(r.supplier_id)
        return r


__all__ = ["TrustBand", "TrustService", "to_out"]

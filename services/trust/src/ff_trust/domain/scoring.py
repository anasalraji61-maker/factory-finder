"""Pure scoring engine: SupplierSignals + ScoringConfig -> Assessment.

Each signal maps to f in [-1, 1] (diminishing returns via saturating curves);
impact = round(weight * f). Score = clamp(baseline + sum(impacts), 0, 100), then hard caps
are applied in order and recorded as negative "cap" factors. Rules:
  * sanctions_hit -> band red, score <= sanctions_cap (20)
  * dispute_rate >= 0.15 -> score <= 49; >= 0.08 -> score <= 69
  * price_vs_market_ratio < 0.4 (too cheap) -> score <= 59
  * fewer than min_signals known signals (and no sanctions hit) -> band unknown
"""

import math

from ff_trust.config import ScoringConfig
from ff_trust.domain.models import Assessment, Factor, FactorKind, TrustBand
from ff_trust.domain.signals import SupplierSignals

SCORABLE = (
    "years_in_business", "verified", "third_party_audit", "transactions_count", "response_rate",
    "rating_avg", "reviews_count", "dispute_rate", "certifications", "domain_age_years",
    "has_physical_address", "contact_consistency", "price_vs_market_ratio", "country_risk",
)  # fmt: skip


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _curve(x: float, k: float, floor: float) -> float:
    """Saturating curve from `floor` at x=0 towards 1 (diminishing returns)."""
    return floor + (1 - floor) * (1 - math.exp(-x / k))


def _price_f(r: float) -> float:
    if r < 0.4:
        return -1.0
    if r < 0.7:
        return -1.0 + (r - 0.4) / 0.3 * 1.3
    if r <= 1.5:
        return 0.3
    return _clip(0.3 - (r - 1.5) * 0.4, -0.5, 0.3)


def _f_values(s: SupplierSignals) -> dict[str, float]:
    f: dict[str, float] = {}
    if s.years_in_business is not None:
        f["years_in_business"] = _curve(s.years_in_business, 5, -0.25)
    if s.verified is not None:
        f["verified"] = 1.0 if s.verified else -0.3
    if s.third_party_audit is not None:
        f["third_party_audit"] = 1.0 if s.third_party_audit else 0.0
    if s.transactions_count is not None:
        f["transactions_count"] = _curve(s.transactions_count, 200, -0.2)
    if s.response_rate is not None:
        f["response_rate"] = _clip((s.response_rate - 0.6) / 0.4)
    if s.rating_avg is not None:
        conf = 0.5 if s.reviews_count is None else min(1.0, s.reviews_count / 20)
        f["rating_avg"] = _clip((s.rating_avg - 3.5) / 1.5) * max(conf, 0.25)
    if s.reviews_count is not None:
        f["reviews_count"] = _curve(s.reviews_count, 100, 0.0)
    if s.dispute_rate is not None:
        f["dispute_rate"] = _clip(0.3 - s.dispute_rate * 13, -1.0, 0.3)
    if s.certifications is not None:
        f["certifications"] = _curve(len({c.strip().upper() for c in s.certifications if c.strip()}), 2, 0.0)
    if s.domain_age_years is not None:
        f["domain_age_years"] = _curve(s.domain_age_years, 4, -0.5)
    if s.has_physical_address is not None:
        f["has_physical_address"] = 1.0 if s.has_physical_address else -1.0
    if s.contact_consistency is not None:
        f["contact_consistency"] = _clip((s.contact_consistency - 0.5) / 0.5)
    if s.price_vs_market_ratio is not None:
        f["price_vs_market_ratio"] = _price_f(s.price_vs_market_ratio)
    if s.country_risk is not None:
        f["country_risk"] = _clip(0.3 - s.country_risk * 1.3)
    return f


def _explain(key: str, s: SupplierSignals, impact: int) -> tuple[str, str]:
    pos = impact > 0
    neu = impact == 0
    sign = "raises" if pos else "lowers" if not neu else "does not change"
    sign_ar = "يرفع" if pos else "يخفض" if not neu else "لا يؤثر على"
    v = getattr(s, key)
    if key == "certifications":
        v = ", ".join(v or []) or "none"
    labels = {
        "years_in_business": ("Years in business", "سنوات العمل"),
        "verified": ("Platform verification", "التوثيق على المنصة"),
        "third_party_audit": ("Third-party factory audit", "تدقيق مصنع من طرف ثالث"),
        "transactions_count": ("Completed transactions", "عدد الصفقات المنجزة"),
        "response_rate": ("Response rate", "معدل الاستجابة"),
        "rating_avg": ("Average rating", "متوسط التقييم"),
        "reviews_count": ("Number of reviews", "عدد التقييمات"),
        "dispute_rate": ("Dispute rate", "نسبة النزاعات"),
        "certifications": ("Certifications", "الشهادات"),
        "domain_age_years": ("Website age (years)", "عمر الموقع (سنوات)"),
        "has_physical_address": ("Verifiable physical address", "عنوان فعلي قابل للتحقق"),
        "contact_consistency": ("Contact details consistency", "اتساق بيانات التواصل"),
        "price_vs_market_ratio": ("Price vs market median", "السعر مقابل متوسط السوق"),
        "country_risk": ("Country risk", "مخاطر البلد"),
    }
    en, ar = labels[key]
    return f"{en} ({v}) {sign} the score.", f"{ar} ({v}) {sign_ar} الدرجة."


def band_for(score: int, cfg: ScoringConfig) -> TrustBand:
    if score >= cfg.green_min:
        return TrustBand.GREEN
    if score >= cfg.yellow_min:
        return TrustBand.YELLOW
    return TrustBand.RED


def assess(signals: SupplierSignals, cfg: ScoringConfig | None = None) -> Assessment:
    cfg = cfg or ScoringConfig()
    fvals = _f_values(signals)
    factors: list[Factor] = []
    total = 0
    for key in SCORABLE:
        if key not in fvals:
            continue
        impact = round(cfg.weights.get(key, 0) * fvals[key])
        total += impact
        en, ar = _explain(key, signals, impact)
        factors.append(Factor(key, impact, en, ar))
    score = int(_clip(cfg.baseline + total, 0, 100))

    caps: list[str] = []

    def apply_cap(key: str, limit: int, en: str, ar: str) -> None:
        nonlocal score
        if score > limit:
            factors.append(Factor(key, limit - score, en, ar, FactorKind.CAP))
            score = limit
            caps.append(key)

    sanctioned = bool(signals.sanctions_hit)
    if sanctioned:
        apply_cap(
            "sanctions_hit", cfg.sanctions_cap,
            f"Supplier matches a sanctions list: score capped at {cfg.sanctions_cap}.",
            f"المورد ضمن قوائم العقوبات: الدرجة محدودة بـ {cfg.sanctions_cap}.",
        )  # fmt: skip
        if "sanctions_hit" not in caps:
            caps.append("sanctions_hit")
            factors.append(Factor("sanctions_hit", 0, "Supplier matches a sanctions list.", "المورد ضمن قوائم العقوبات.", FactorKind.CAP))
    d = signals.dispute_rate
    if d is not None and d >= cfg.dispute_severe_rate:
        apply_cap("dispute_rate_cap", cfg.dispute_severe_cap,
                  f"Very high dispute rate: score capped at {cfg.dispute_severe_cap}.",
                  f"نسبة نزاعات مرتفعة جدا: الدرجة محدودة بـ {cfg.dispute_severe_cap}.")  # fmt: skip
    elif d is not None and d >= cfg.dispute_high_rate:
        apply_cap("dispute_rate_cap", cfg.dispute_high_cap,
                  f"High dispute rate: score capped at {cfg.dispute_high_cap}.",
                  f"نسبة نزاعات مرتفعة: الدرجة محدودة بـ {cfg.dispute_high_cap}.")  # fmt: skip
    p = signals.price_vs_market_ratio
    if p is not None and p < cfg.too_cheap_ratio:
        apply_cap("price_too_low_cap", cfg.too_cheap_cap,
                  f"Price far below market (possible scam): capped at {cfg.too_cheap_cap}.",
                  f"السعر أقل بكثير من السوق (احتمال احتيال): الدرجة محدودة بـ {cfg.too_cheap_cap}.")  # fmt: skip

    used = len(fvals) + (1 if signals.sanctions_hit is not None else 0)
    insufficient = used < cfg.min_signals and not sanctioned
    if sanctioned:
        band = TrustBand.RED
    elif insufficient:
        band = TrustBand.UNKNOWN
        factors.append(Factor(
            "insufficient_data", 0,
            f"Only {used} signals available (need {cfg.min_signals}); no verdict.",
            f"تتوفر {used} إشارات فقط (المطلوب {cfg.min_signals}); لا يوجد حكم.",
            FactorKind.INFO,
        ))  # fmt: skip
    else:
        band = band_for(score, cfg)
    return Assessment(
        score=score, band=band, factors=tuple(factors), baseline=cfg.baseline,
        confidence=round(min(1.0, used / (len(SCORABLE) + 1)), 2), signals_used=used,
        signals_total=len(SCORABLE) + 1, insufficient_signals=insufficient,
        caps_applied=tuple(caps), model_version=cfg.model_version,
    )  # fmt: skip

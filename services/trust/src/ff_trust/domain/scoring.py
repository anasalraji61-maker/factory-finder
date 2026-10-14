"""Pure scoring engine: SupplierSignals + ScoringConfig -> Assessment.

Each signal maps to f in [-1, 1] (diminishing returns via saturating curves);
impact = round(weight * f). Score = clamp(baseline + sum(impacts), 0, 100), then hard caps
are applied in order and recorded as negative "cap" factors. Rules:
  * sanctions_hit or blocked -> band red, score <= 20 (hard fail, clear explanation)
  * dispute_rate (recency-blended) >= 0.15 -> score <= 49; >= 0.08 -> score <= 69
  * price_vs_market_ratio < 0.4 (too cheap) -> score <= 59
  * fewer than min_signals known signals (and no hard fail) -> band unknown
Missing data never lowers the score: it lowers `confidence` (0-100) and is listed in `data_gaps`.
Review rating and deal completion use Bayesian shrinkage towards a prior so small samples
cannot swing the score. Expired certificates do not count.
"""

import math
from datetime import UTC, date, datetime, timedelta

from ff_trust.config import ScoringConfig
from ff_trust.domain.models import Assessment, DataGap, Factor, FactorKind, TrustBand
from ff_trust.domain.signals import ReviewSummary, SupplierSignals

SCORABLE = (
    "years_in_business", "verified", "third_party_audit", "transactions_count", "response_rate",
    "rating_avg", "reviews_count", "dispute_rate", "certifications", "domain_age_years",
    "has_physical_address", "contact_consistency", "price_vs_market_ratio", "country_risk",
    "business_license_status", "storefront_age_years", "repeat_buyer_rate", "response_time_hours",
    "refund_rate", "deal_outcomes", "confirmed_reports", "platform_reviews",
)  # fmt: skip

LABELS = {
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
    "business_license_status": ("Business licence / registry check", "التحقق من الترخيص التجاري والسجل"),
    "storefront_age_years": ("Storefront age (years)", "عمر المتجر (سنوات)"),
    "repeat_buyer_rate": ("Repeat-buyer rate", "نسبة المشترين المتكررين"),
    "response_time_hours": ("Typical response time (hours)", "زمن الاستجابة المعتاد (ساعات)"),
    "refund_rate": ("Refund rate", "نسبة الاسترجاع"),
    "deal_outcomes": ("On-platform deal outcomes", "نتائج الصفقات على المنصة"),
    "confirmed_reports": ("Confirmed buyer reports", "بلاغات المشترين المؤكدة"),
    "platform_reviews": ("Verified-purchase reviews", "تقييمات المشترين الموثقة"),
}
# confirmed_reports is a penalty-only signal: its absence is the normal state, not a data gap.
# platform_reviews is an optional enrichment (only present when the rfq source is on): never a data gap.
EVIDENCE = tuple(k for k in SCORABLE if k not in ("confirmed_reports", "platform_reviews"))
GAP_ONLY = {"sanctions_hit": ("Sanctions screening not run", "لم يتم فحص قوائم العقوبات")}
_LICENSE_F = {"verified": 1.0, "pending": 0.1, "unverified": -0.3, "expired": -0.6, "mismatch": -1.0}


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


def _response_time_f(h: float) -> float:
    """<=2h -> +1, 12h -> 0, >=48h -> -1 (piecewise linear, non-increasing)."""
    if h <= 2:
        return 1.0
    if h <= 12:
        return 1.0 - (h - 2) / 10
    return _clip(-(h - 12) / 36)


def _norm_cert(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalnum())


def cert_status(s: SupplierSignals, today: date, soon_days: int = 60) -> tuple[set[str], set[str], set[str]]:
    """(valid, expired, expiring_soon) normalised certificate names. A dated record overrides a bare name."""
    records = s.certification_records or []
    rec_names = {_norm_cert(r.name) for r in records}
    valid = {_norm_cert(c) for c in (s.certifications or []) if _norm_cert(c)} - rec_names
    expired: set[str] = set()
    soon: set[str] = set()
    for r in records:
        n = _norm_cert(r.name)
        if not n:
            continue
        if r.expires_on is not None and r.expires_on < today:
            expired.add(n)
        else:
            valid.add(n)
            if r.expires_on is not None and r.expires_on <= today + timedelta(days=soon_days):
                soon.add(n)
    return valid, expired - valid, soon


def effective_dispute_rate(s: SupplierSignals, cfg: ScoringConfig) -> float | None:
    """Lifetime dispute rate blended with the recent (90 day) one, so recent disputes weigh more."""
    d, r = s.dispute_rate, s.dispute_rate_recent
    if d is None:
        return r
    if r is None:
        return d
    w = cfg.dispute_recent_weight
    return (1 - w) * d + w * r


def _deal_rate(s: SupplierSignals, cfg: ScoringConfig) -> tuple[float, int] | None:
    if s.deals_completed is None and s.deals_cancelled is None:
        return None
    done, canc = s.deals_completed or 0, s.deals_cancelled or 0
    if done + canc == 0:
        return None
    n = done + canc
    return (done + cfg.deal_prior_rate * cfg.deal_prior_weight) / (n + cfg.deal_prior_weight), n


def adjusted_rating(avg: float, n: int | None, cfg: ScoringConfig) -> float:
    """Bayesian mean: few reviews pull the rating towards the prior. Unknown count counts as 5."""
    n_eff = 5 if n is None else n
    return (n_eff * avg + cfg.review_prior_weight * cfg.review_prior_mean) / (n_eff + cfg.review_prior_weight)


def _summary_average(rs: ReviewSummary) -> float | None:
    if rs.average is not None:
        return rs.average
    h = rs.histogram or {}
    n = sum(v for k, v in h.items() if k in "12345" and v > 0)
    return sum(int(k) * v for k, v in h.items() if k in "12345" and v > 0) / n if n else None


def platform_reviews_f(rs: ReviewSummary, cfg: ScoringConfig) -> float | None:
    """Shrunk average (+ sub-ratings), then linearly dampened below `platform_review_full_n` reviews."""
    avg = _summary_average(rs)
    if rs.count <= 0 or avg is None:
        return None
    w = cfg.platform_review_prior_weight
    adj = (rs.count * avg + w * cfg.review_prior_mean) / (rs.count + w)
    f = _clip((adj - cfg.review_prior_mean) / 1.2)
    subs = [v for v in (rs.sub_ratings or {}).values() if v is not None and 0 <= v <= 5]
    if subs:
        sub_adj = (rs.count * (sum(subs) / len(subs)) + w * cfg.review_prior_mean) / (rs.count + w)
        f = (1 - cfg.platform_review_sub_share) * f + cfg.platform_review_sub_share * _clip((sub_adj - cfg.review_prior_mean) / 1.2)
    return _clip(f) * min(1.0, rs.count / max(1, cfg.platform_review_full_n))


def _f_values(s: SupplierSignals, cfg: ScoringConfig, today: date) -> dict[str, float]:
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
        f["rating_avg"] = _clip((adjusted_rating(s.rating_avg, s.reviews_count, cfg) - cfg.review_prior_mean) / 1.2)
    if s.reviews_count is not None:
        f["reviews_count"] = _curve(s.reviews_count, 100, 0.0)
    d = effective_dispute_rate(s, cfg)
    if d is not None:
        f["dispute_rate"] = _clip(0.3 - d * 13, -1.0, 0.3)
    if s.certifications is not None or s.certification_records is not None:
        valid, expired, _ = cert_status(s, today, cfg.cert_expiring_days)
        v = _curve(len(valid), 2, 0.0)
        f["certifications"] = v if (valid or not expired) else -0.3
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
    if s.business_license_status is not None:
        f["business_license_status"] = _LICENSE_F[s.business_license_status]
    if s.storefront_age_years is not None:
        f["storefront_age_years"] = _curve(s.storefront_age_years, 3, -0.5)
    if s.repeat_buyer_rate is not None:
        f["repeat_buyer_rate"] = _clip((s.repeat_buyer_rate - 0.25) / 0.3)
    if s.response_time_hours is not None:
        f["response_time_hours"] = _response_time_f(s.response_time_hours)
    if s.refund_rate is not None:
        f["refund_rate"] = _clip(0.3 - s.refund_rate * 8, -1.0, 0.3)
    dr = _deal_rate(s, cfg)
    if dr is not None:
        f["deal_outcomes"] = _clip((dr[0] - cfg.deal_prior_rate) / 0.15)
    if s.confirmed_reports is not None:
        f["confirmed_reports"] = -min(1.0, s.confirmed_reports / 3)
    if s.review_summary is not None:
        pf = platform_reviews_f(s.review_summary, cfg)
        if pf is not None:
            f["platform_reviews"] = pf
    return f


def _value_text(key: str, s: SupplierSignals, cfg: ScoringConfig, today: date) -> str:
    if key == "certifications":
        valid, expired, _ = cert_status(s, today, cfg.cert_expiring_days)
        txt = ", ".join(sorted(valid)) or "none valid"
        return txt + (f"; expired: {', '.join(sorted(expired))}" if expired else "")
    if key == "rating_avg":
        return f"{s.rating_avg} from {s.reviews_count if s.reviews_count is not None else '?'} reviews, adjusted {adjusted_rating(s.rating_avg, s.reviews_count, cfg):.2f}"
    if key == "dispute_rate":
        d = effective_dispute_rate(s, cfg)
        return f"{d:.3f}" + (" recency-weighted" if s.dispute_rate_recent is not None else "")
    if key == "platform_reviews":
        rs = s.review_summary
        deals = f", deals={rs.completed_deals}" if rs.completed_deals else ""
        return f"{_summary_average(rs):.2f}/5, n={rs.count}{deals}" + (", small sample dampened" if rs.count < cfg.platform_review_full_n else "")
    if key == "deal_outcomes":
        return f"{s.deals_completed or 0} completed / {s.deals_cancelled or 0} cancelled"
    return str(getattr(s, key))


def _explain(key: str, s: SupplierSignals, impact: int, cfg: ScoringConfig, today: date) -> tuple[str, str]:
    pos = impact > 0
    neu = impact == 0
    sign = "raises" if pos else "lowers" if not neu else "does not change"
    sign_ar = "يرفع" if pos else "يخفض" if not neu else "لا يؤثر على"
    en, ar = LABELS[key]
    v = _value_text(key, s, cfg, today)
    return f"{en} ({v}) {sign} the score.", f"{ar} ({v}) {sign_ar} الدرجة."


def band_for(score: int, cfg: ScoringConfig) -> TrustBand:
    if score >= cfg.green_min:
        return TrustBand.GREEN
    if score >= cfg.yellow_min:
        return TrustBand.YELLOW
    return TrustBand.RED


def confidence_for(s: SupplierSignals, fvals: dict[str, float], cfg: ScoringConfig) -> int:
    """0-100: weighted coverage of known signals, scaled by sample depth (reviews/transactions/deals)."""
    total_w = sum(cfg.weights.get(k, 0) for k in EVIDENCE) or 1.0
    coverage = sum(cfg.weights.get(k, 0) for k in fvals if k in EVIDENCE) / total_w
    depth_parts = []
    if s.reviews_count is not None:
        depth_parts.append(min(1.0, s.reviews_count / 30))
    if s.transactions_count is not None:
        depth_parts.append(min(1.0, s.transactions_count / 50))
    dr = _deal_rate(s, cfg)
    if dr is not None:
        depth_parts.append(min(1.0, dr[1] / 20))
    depth = sum(depth_parts) / len(depth_parts) if depth_parts else 0.5
    return int(round(100 * min(1.0, coverage * (0.7 + 0.3 * depth))))


def data_gaps_for(s: SupplierSignals, fvals: dict[str, float], cfg: ScoringConfig) -> tuple[DataGap, ...]:
    """Missing signals, most influential (highest weight) first. Bilingual."""
    gaps = [
        DataGap(k, f"Missing: {LABELS[k][0]}", f"غير متوفر: {LABELS[k][1]}")
        for k in sorted((k for k in EVIDENCE if k not in fvals), key=lambda k: (-cfg.weights.get(k, 0), k))
    ]  # fmt: skip
    if s.sanctions_hit is None:
        en, ar = GAP_ONLY["sanctions_hit"]
        gaps.append(DataGap("sanctions_hit", en, ar))
    return tuple(gaps)


def assess(signals: SupplierSignals, cfg: ScoringConfig | None = None, today: date | None = None) -> Assessment:
    cfg = cfg or ScoringConfig()
    today = today or datetime.now(UTC).date()
    fvals = _f_values(signals, cfg, today)
    factors: list[Factor] = []
    flags: list[str] = []
    total = 0
    for key in SCORABLE:
        if key not in fvals:
            continue
        impact = round(cfg.weights.get(key, 0) * fvals[key])
        total += impact
        en, ar = _explain(key, signals, impact, cfg, today)
        factors.append(Factor(key, impact, en, ar))
    score = int(_clip(cfg.baseline + total, 0, 100))

    caps: list[str] = []

    def apply_cap(key: str, limit: int, en: str, ar: str) -> None:
        nonlocal score
        if score > limit:
            factors.append(Factor(key, limit - score, en, ar, FactorKind.CAP))
            score = limit
            caps.append(key)

    hard_fail = False
    for key, hit, cap, en, ar in (
        ("sanctions_hit", signals.sanctions_hit, cfg.sanctions_cap,
         "Supplier matches a sanctions list", "المورد ضمن قوائم العقوبات"),
        ("blocked_flag", signals.blocked, cfg.hard_fail_cap,
         "Supplier is blocked by the platform / compliance", "المورد محظور من المنصة / الامتثال"),
    ):  # fmt: skip
        if not hit:
            continue
        hard_fail = True
        flags.append(key)
        apply_cap(key, cap, f"{en}: score capped at {cap}.", f"{ar}: الدرجة محدودة بـ {cap}.")
        if key not in caps:
            caps.append(key)
            factors.append(Factor(key, 0, f"{en}.", f"{ar}.", FactorKind.CAP))
    d = effective_dispute_rate(signals, cfg)
    if d is not None and signals.dispute_rate is not None:
        d = max(d, signals.dispute_rate)  # recent improvement never lifts a cap earned by the lifetime rate
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
    if p is not None and (p < cfg.price_anomaly_low or p > cfg.price_anomaly_high):
        flags.append("price_anomaly")
        factors.append(Factor(
            "price_anomaly", 0,
            f"Price anomaly: offers are {p:.2f}x the market median.",
            f"شذوذ سعري: العروض بنسبة {p:.2f} من متوسط السوق.", FactorKind.INFO,
        ))  # fmt: skip
    if signals.certifications is not None or signals.certification_records is not None:
        _, expired, soon = cert_status(signals, today, cfg.cert_expiring_days)
        if expired:
            flags.append("certification_expired")
            factors.append(Factor(
                "certification_expired", 0,
                f"Expired certificates are ignored: {', '.join(sorted(expired))}.",
                f"شهادات منتهية الصلاحية لا تُحتسب: {', '.join(sorted(expired))}.", FactorKind.INFO,
            ))  # fmt: skip
        if soon:
            flags.append("certification_expiring")
            factors.append(Factor(
                "certification_expiring", 0,
                f"Certificates expiring within {cfg.cert_expiring_days} days: {', '.join(sorted(soon))}.",
                f"شهادات تنتهي خلال {cfg.cert_expiring_days} يوما: {', '.join(sorted(soon))}.", FactorKind.INFO,
            ))  # fmt: skip

    used = len(fvals) + (1 if signals.sanctions_hit is not None else 0)
    insufficient = used < cfg.min_signals and not hard_fail
    if hard_fail:
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
        confidence=confidence_for(signals, fvals, cfg), signals_used=used,
        signals_total=len(SCORABLE) + 1, insufficient_signals=insufficient,
        caps_applied=tuple(caps), model_version=cfg.model_version,
        data_gaps=data_gaps_for(signals, fvals, cfg), flags=tuple(flags),
    )  # fmt: skip

"""Result types of the trust scoring engine (pure data, no I/O)."""

from dataclasses import dataclass
from enum import Enum


class TrustBand(str, Enum):
    """Traffic-light band. ``unknown`` means there was not enough data for a verdict."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class FactorKind(str, Enum):
    """What a factor in the explanation list represents."""

    SIGNAL = "signal"  # signed contribution of one trust signal
    CAP = "cap"  # hard rule that limits the score (impact <= 0)
    INFO = "info"  # zero-impact note, e.g. "not enough data"


@dataclass(frozen=True, slots=True)
class Factor:
    """One line of the explanation: a signed integer contribution plus bilingual text."""

    key: str
    impact: int
    explanation: str
    explanation_ar: str
    kind: FactorKind = FactorKind.SIGNAL


@dataclass(frozen=True, slots=True)
class Assessment:
    """Full outcome of scoring one set of signals.

    Invariant (checked by tests)::

        score == clamp(baseline + sum(signal impacts), 0, 100) + sum(cap impacts)
    """

    score: int
    band: TrustBand
    factors: tuple[Factor, ...]
    baseline: int
    confidence: float
    signals_used: int
    signals_total: int
    insufficient_signals: bool
    caps_applied: tuple[str, ...]
    model_version: str

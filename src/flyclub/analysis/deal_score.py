"""Deterministic and explainable Fly Club Deal Score."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection


class DealClassification(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    NORMAL = "NORMAL"
    REASONABLE = "REASONABLE"
    INTERESTING = "INTERESTING"
    GREAT = "GREAT"
    EXCEPTIONAL = "EXCEPTIONAL"


class ScoreComponentName(StrEnum):
    PERCENTILE = "PERCENTILE"
    MEDIAN_DISCOUNT = "MEDIAN_DISCOUNT"
    RECORDED_LOW_PROXIMITY = "RECORDED_LOW_PROXIMITY"
    RECENT_DROP = "RECENT_DROP"
    TREND = "TREND"


class RecentDropBasis(StrEnum):
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"
    LAST_ALERT = "LAST_ALERT"


@dataclass(frozen=True, slots=True)
class RecentDropSignal:
    basis: RecentDropBasis
    drop_percent: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.drop_percent, Decimal):
            raise TypeError("drop_percent must use Decimal")
        if not self.drop_percent.is_finite():
            raise ValueError("drop_percent must be finite")


@dataclass(frozen=True, slots=True)
class DealScoreWeights:
    percentile: int = 40
    median_discount: int = 25
    recorded_low_proximity: int = 15
    recent_drop: int = 10
    trend: int = 10

    def __post_init__(self) -> None:
        values = (
            self.percentile,
            self.median_discount,
            self.recorded_low_proximity,
            self.recent_drop,
            self.trend,
        )
        if any(value < 0 or value > 100 for value in values):
            raise ValueError("Deal Score weights must be between 0 and 100")
        if sum(values) != 100:
            raise ValueError("Deal Score weights must total 100")


@dataclass(frozen=True, slots=True)
class DealScoreScale:
    """Full-credit signal levels kept explicit so scoring remains testable."""

    median_discount_full_score_percent: Decimal = Decimal("25")
    recorded_low_zero_score_percent: Decimal = Decimal("20")
    recent_drop_full_score_percent: Decimal = Decimal("10")
    trend_decline_full_score_percent: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        values = (
            self.median_discount_full_score_percent,
            self.recorded_low_zero_score_percent,
            self.recent_drop_full_score_percent,
            self.trend_decline_full_score_percent,
        )
        if any(value <= 0 or not value.is_finite() for value in values):
            raise ValueError("Deal Score scale percentages must be finite and positive")


DEFAULT_DEAL_SCORE_WEIGHTS = DealScoreWeights()
DEFAULT_DEAL_SCORE_SCALE = DealScoreScale()


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: ScoreComponentName
    points: Decimal
    maximum_points: int
    metric_percent: Decimal
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DealScoreResult:
    score: int | None
    classification: DealClassification
    confidence: ConfidenceLevel
    provisional: bool
    components: tuple[ScoreComponent, ...]


def _clamp_ratio(value: Decimal, full_score_value: Decimal) -> Decimal:
    return min(max(value / full_score_value, Decimal(0)), Decimal(1))


def _component(
    name: ScoreComponentName,
    maximum: int,
    metric: Decimal,
    ratio: Decimal,
    detail: str | None = None,
) -> ScoreComponent:
    points = (Decimal(maximum) * min(max(ratio, Decimal(0)), Decimal(1))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return ScoreComponent(
        name=name,
        points=points,
        maximum_points=maximum,
        metric_percent=metric,
        detail=detail,
    )


def _classification(score: int) -> DealClassification:
    if score < 40:
        return DealClassification.NORMAL
    if score < 60:
        return DealClassification.REASONABLE
    if score < 75:
        return DealClassification.INTERESTING
    if score < 90:
        return DealClassification.GREAT
    return DealClassification.EXCEPTIONAL


def calculate_deal_score(
    current_price: Decimal,
    statistics: PriceStatistics,
    *,
    recent_drop: RecentDropSignal | None = None,
    trend: TrendAnalysis | None = None,
    weights: DealScoreWeights = DEFAULT_DEAL_SCORE_WEIGHTS,
    scale: DealScoreScale = DEFAULT_DEAL_SCORE_SCALE,
) -> DealScoreResult:
    """Score price quality without using days-to-departure or other urgency signals."""

    if not isinstance(current_price, Decimal):
        raise TypeError("current_price must use Decimal")
    if not current_price.is_finite() or current_price <= 0:
        raise ValueError("current_price must be finite and greater than zero")
    if statistics.confidence is ConfidenceLevel.INSUFFICIENT:
        return DealScoreResult(
            score=None,
            classification=DealClassification.UNAVAILABLE,
            confidence=statistics.confidence,
            provisional=False,
            components=(),
        )

    if (
        statistics.percentile_rank is None
        or statistics.p50 is None
        or statistics.recorded_low is None
    ):
        raise ValueError("eligible statistics must contain rank, median, and recorded low")

    rank = statistics.percentile_rank
    median_discount = max(
        (statistics.p50 - current_price) * Decimal(100) / statistics.p50,
        Decimal(0),
    )
    premium_above_low = max(
        (current_price - statistics.recorded_low) * Decimal(100) / statistics.recorded_low,
        Decimal(0),
    )
    objective_drop = max(
        recent_drop.drop_percent if recent_drop is not None else Decimal(0),
        Decimal(0),
    )
    trend_decline = Decimal(0)
    if (
        trend is not None
        and trend.direction is TrendDirection.FALLING
        and trend.change_percent is not None
    ):
        trend_decline = -trend.change_percent

    components = (
        _component(
            ScoreComponentName.PERCENTILE,
            weights.percentile,
            rank,
            (Decimal(100) - rank) / Decimal(100),
        ),
        _component(
            ScoreComponentName.MEDIAN_DISCOUNT,
            weights.median_discount,
            median_discount,
            _clamp_ratio(median_discount, scale.median_discount_full_score_percent),
        ),
        _component(
            ScoreComponentName.RECORDED_LOW_PROXIMITY,
            weights.recorded_low_proximity,
            premium_above_low,
            Decimal(1) - _clamp_ratio(premium_above_low, scale.recorded_low_zero_score_percent),
        ),
        _component(
            ScoreComponentName.RECENT_DROP,
            weights.recent_drop,
            objective_drop,
            _clamp_ratio(objective_drop, scale.recent_drop_full_score_percent),
            recent_drop.basis.value if recent_drop is not None else None,
        ),
        _component(
            ScoreComponentName.TREND,
            weights.trend,
            trend_decline,
            _clamp_ratio(trend_decline, scale.trend_decline_full_score_percent),
        ),
    )
    raw_score = sum((component.points for component in components), start=Decimal(0))
    score = int(raw_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return DealScoreResult(
        score=score,
        classification=_classification(score),
        confidence=statistics.confidence,
        provisional=statistics.confidence is ConfidenceLevel.LOW,
        components=components,
    )

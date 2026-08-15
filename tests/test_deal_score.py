from __future__ import annotations

from decimal import Decimal

import pytest

from flyclub.analysis.deal_score import (
    DealClassification,
    DealScoreWeights,
    RecentDropBasis,
    RecentDropSignal,
    ScoreComponentName,
    calculate_deal_score,
)
from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection


def _statistics(
    *,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    rank: str = "5",
    median: str = "100",
    low: str = "80",
) -> PriceStatistics:
    return PriceStatistics(
        sample_size=101,
        confidence=confidence,
        p10=Decimal("85"),
        p50=Decimal(median),
        p90=Decimal("130"),
        percentile_rank=Decimal(rank),
        recorded_low=Decimal(low),
    )


def _falling_trend(change: str = "-5") -> TrendAnalysis:
    return TrendAnalysis(
        sample_size=8,
        direction=TrendDirection.FALLING,
        change_percent=Decimal(change),
        previous_median=Decimal("100"),
        recent_median=Decimal("95"),
    )


def _drop(
    percent: str, basis: RecentDropBasis = RecentDropBasis.TWENTY_FOUR_HOURS
) -> RecentDropSignal:
    return RecentDropSignal(basis=basis, drop_percent=Decimal(percent))


def test_approved_weights_total_one_hundred_without_urgency_component() -> None:
    weights = DealScoreWeights()

    assert weights == DealScoreWeights(40, 25, 15, 10, 10)
    assert not hasattr(weights, "days_to_departure")


def test_score_is_deterministic_explainable_and_bounded() -> None:
    result = calculate_deal_score(
        Decimal("75"),
        _statistics(),
        recent_drop=_drop("10"),
        trend=_falling_trend(),
    )

    assert result.score == 93
    assert result.classification is DealClassification.EXCEPTIONAL
    assert result.confidence is ConfidenceLevel.HIGH
    assert result.provisional is False
    assert [component.name for component in result.components] == [
        ScoreComponentName.PERCENTILE,
        ScoreComponentName.MEDIAN_DISCOUNT,
        ScoreComponentName.RECORDED_LOW_PROXIMITY,
        ScoreComponentName.RECENT_DROP,
        ScoreComponentName.TREND,
    ]
    assert sum(component.maximum_points for component in result.components) == 100
    recent_component = next(
        component
        for component in result.components
        if component.name is ScoreComponentName.RECENT_DROP
    )
    assert recent_component.detail == RecentDropBasis.TWENTY_FOUR_HOURS.value


def test_low_confidence_score_is_explicitly_provisional() -> None:
    result = calculate_deal_score(
        Decimal("80"),
        _statistics(confidence=ConfidenceLevel.LOW),
    )

    assert result.score is not None
    assert result.confidence is ConfidenceLevel.LOW
    assert result.provisional is True


def test_insufficient_history_does_not_produce_a_score() -> None:
    result = calculate_deal_score(
        Decimal("80"),
        PriceStatistics(
            sample_size=11,
            confidence=ConfidenceLevel.INSUFFICIENT,
            p10=Decimal("85"),
            p50=Decimal("100"),
            p90=Decimal("120"),
            percentile_rank=Decimal("5"),
            recorded_low=Decimal("80"),
        ),
    )

    assert result.score is None
    assert result.classification is DealClassification.UNAVAILABLE
    assert result.components == ()


def test_recent_drop_and_historical_trend_are_independent_components() -> None:
    without_drop = calculate_deal_score(
        Decimal("90"),
        _statistics(rank="20"),
        recent_drop=_drop("0"),
        trend=_falling_trend("-10"),
    )
    without_trend = calculate_deal_score(
        Decimal("90"),
        _statistics(rank="20"),
        recent_drop=_drop("10", RecentDropBasis.LAST_ALERT),
        trend=TrendAnalysis(8, TrendDirection.STABLE, Decimal("0"), Decimal("100"), Decimal("100")),
    )

    first = {component.name: component.points for component in without_drop.components}
    second = {component.name: component.points for component in without_trend.components}
    assert first[ScoreComponentName.RECENT_DROP] == 0
    assert first[ScoreComponentName.TREND] == 10
    assert second[ScoreComponentName.RECENT_DROP] == 10
    assert second[ScoreComponentName.TREND] == 0


@pytest.mark.parametrize(
    ("score_rank", "expected"),
    [
        ("100", DealClassification.NORMAL),
        ("50", DealClassification.REASONABLE),
        ("30", DealClassification.INTERESTING),
        ("20", DealClassification.GREAT),
        ("5", DealClassification.EXCEPTIONAL),
    ],
)
def test_score_classification_thresholds(score_rank: str, expected: DealClassification) -> None:
    result = calculate_deal_score(
        Decimal("120"),
        _statistics(rank=score_rank, median="100", low="80"),
        weights=DealScoreWeights(
            percentile=100,
            median_discount=0,
            recorded_low_proximity=0,
            recent_drop=0,
            trend=0,
        ),
    )

    assert result.classification is expected


def test_weights_must_total_one_hundred() -> None:
    with pytest.raises(ValueError, match="total 100"):
        DealScoreWeights(percentile=39)


def test_score_rejects_non_decimal_current_price() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        calculate_deal_score(80.0, _statistics())  # type: ignore[arg-type]


def test_recent_drop_signal_requires_decimal() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        RecentDropSignal(RecentDropBasis.LAST_ALERT, 10.0)  # type: ignore[arg-type]

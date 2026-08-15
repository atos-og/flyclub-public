from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flyclub.alerts.engine import (
    AlertDecision,
    AlertPolicy,
    AlertReason,
    decide_alert,
)
from flyclub.analysis.deal_score import DealClassification, DealScoreResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection
from flyclub.models import PriceObservation

NOW = datetime(2027, 1, 10, 12, tzinfo=UTC)


def _evaluation(
    *,
    sample_size: int = 31,
    confidence: ConfidenceLevel = ConfidenceLevel.MODERATE,
    score: int | None = 90,
    recorded_low: str = "90",
) -> RoutePriceEvaluation:
    statistics = PriceStatistics(
        sample_size=sample_size,
        confidence=confidence,
        p10=Decimal("95") if sample_size else None,
        p50=Decimal("110") if sample_size else None,
        p90=Decimal("130") if sample_size else None,
        percentile_rank=Decimal("5") if sample_size else None,
        recorded_low=Decimal(recorded_low) if sample_size else None,
    )
    deal_score = DealScoreResult(
        score=score,
        classification=(
            DealClassification.UNAVAILABLE
            if score is None
            else DealClassification.EXCEPTIONAL
            if score >= 90
            else DealClassification.REASONABLE
        ),
        confidence=confidence,
        provisional=confidence is ConfidenceLevel.LOW,
        components=(),
    )
    return RoutePriceEvaluation(
        statistics=statistics,
        trend=TrendAnalysis(
            sample_size=8,
            direction=TrendDirection.STABLE,
            change_percent=Decimal("0"),
            previous_median=Decimal("100"),
            recent_median=Decimal("100"),
        ),
        recent_drop=None,
        deal_score=deal_score,
    )


def _decide(
    *,
    current: str = "80",
    evaluation: RoutePriceEvaluation | None = None,
    target: str | None = None,
    last_price: str | None = None,
    last_age_hours: int = 48,
) -> object:
    last_alert = (
        None
        if last_price is None
        else PriceObservation(
            price=Decimal(last_price),
            observed_at=NOW - timedelta(hours=last_age_hours),
        )
    )
    return decide_alert(
        current_price=Decimal(current),
        current_at=NOW,
        evaluation=evaluation or _evaluation(),
        alert_price=Decimal(target) if target is not None else None,
        last_sent_alert=last_alert,
        policy=AlertPolicy(),
    )


def test_manual_price_target_can_alert_during_cold_start() -> None:
    result = _decide(
        current="80",
        evaluation=_evaluation(sample_size=0, confidence=ConfidenceLevel.INSUFFICIENT, score=None),
        target="85",
    )

    assert result.decision is AlertDecision.SEND
    assert result.reasons == (AlertReason.PRICE_TARGET,)


def test_cold_start_without_manual_target_is_suppressed() -> None:
    result = _decide(
        evaluation=_evaluation(sample_size=0, confidence=ConfidenceLevel.INSUFFICIENT, score=None)
    )

    assert result.decision is AlertDecision.SUPPRESS
    assert result.reasons == (AlertReason.NO_TRIGGER,)


def test_low_confidence_exceptional_score_needs_corroboration() -> None:
    result = _decide(
        current="100",
        evaluation=_evaluation(
            sample_size=12,
            confidence=ConfidenceLevel.LOW,
            score=94,
            recorded_low="90",
        ),
    )

    assert result.decision is AlertDecision.SUPPRESS
    assert AlertReason.EXCEPTIONAL_DEAL in result.reasons
    assert AlertReason.LOW_CONFIDENCE_UNCORROBORATED in result.reasons


def test_low_confidence_exceptional_new_low_is_consolidated_and_sent() -> None:
    result = _decide(
        current="80",
        evaluation=_evaluation(
            sample_size=12,
            confidence=ConfidenceLevel.LOW,
            score=94,
            recorded_low="90",
        ),
    )

    assert result.decision is AlertDecision.SEND
    assert result.reasons == (AlertReason.NEW_LOW, AlertReason.EXCEPTIONAL_DEAL)


def test_new_low_requires_minimum_statistical_sample() -> None:
    result = _decide(
        current="80",
        evaluation=_evaluation(
            sample_size=11,
            confidence=ConfidenceLevel.INSUFFICIENT,
            score=None,
            recorded_low="90",
        ),
    )

    assert result.decision is AlertDecision.SUPPRESS
    assert result.reasons == (AlertReason.NO_TRIGGER,)


def test_significant_drop_requires_absolute_and_percentage_thresholds() -> None:
    amount_only = _decide(current="9900", evaluation=_evaluation(score=50), last_price="10000")
    both = _decide(current="800", evaluation=_evaluation(score=50), last_price="1000")

    assert amount_only.decision is AlertDecision.SUPPRESS
    assert AlertReason.SIGNIFICANT_DROP not in amount_only.reasons
    assert both.decision is AlertDecision.SEND
    assert both.reasons == (AlertReason.SIGNIFICANT_DROP,)


def test_cooldown_suppresses_repeated_opportunity() -> None:
    result = _decide(current="80", target="85", last_price="80", last_age_hours=3)

    assert result.decision is AlertDecision.SUPPRESS
    assert AlertReason.PRICE_TARGET in result.reasons
    assert AlertReason.COOLDOWN_ACTIVE in result.reasons


def test_new_significant_drop_bypasses_cooldown() -> None:
    result = _decide(
        current="800", evaluation=_evaluation(score=50), last_price="1000", last_age_hours=3
    )

    assert result.decision is AlertDecision.SEND
    assert result.reasons == (AlertReason.SIGNIFICANT_DROP,)


def test_opportunity_can_repeat_after_cooldown() -> None:
    result = _decide(current="80", target="85", last_price="80", last_age_hours=25)

    assert result.decision is AlertDecision.SEND
    assert AlertReason.PRICE_TARGET in result.reasons


def test_alert_policy_has_no_days_to_departure_urgency_field() -> None:
    assert not hasattr(AlertPolicy(), "days_to_departure")

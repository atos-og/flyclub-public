"""Pure consolidated alert decisions with confidence and cooldown safeguards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel
from flyclub.analysis.trend import price_drop_percent
from flyclub.models import PriceObservation


class AlertDecision(StrEnum):
    SEND = "SEND"
    SUPPRESS = "SUPPRESS"


class AlertReason(StrEnum):
    PRICE_TARGET = "PRICE_TARGET"
    NEW_LOW = "NEW_LOW"
    EXCEPTIONAL_DEAL = "EXCEPTIONAL_DEAL"
    SIGNIFICANT_DROP = "SIGNIFICANT_DROP"
    LOW_CONFIDENCE_UNCORROBORATED = "LOW_CONFIDENCE_UNCORROBORATED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    NO_TRIGGER = "NO_TRIGGER"


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    exceptional_score: int = 90
    cooldown_hours: int = 24
    min_drop_amount: Decimal = Decimal("100")
    min_drop_percent: Decimal = Decimal("5")
    min_score_samples: int = 12

    def __post_init__(self) -> None:
        if not 0 <= self.exceptional_score <= 100:
            raise ValueError("exceptional_score must be between 0 and 100")
        if self.cooldown_hours < 0:
            raise ValueError("cooldown_hours must not be negative")
        if self.min_drop_amount < 0 or self.min_drop_percent < 0:
            raise ValueError("minimum drops must not be negative")
        if self.min_score_samples < 1:
            raise ValueError("min_score_samples must be at least 1")


@dataclass(frozen=True, slots=True)
class AlertResult:
    decision: AlertDecision
    reasons: tuple[AlertReason, ...]
    drop_amount: Decimal | None = None
    drop_percent: Decimal | None = None


def _ordered_reasons(reasons: set[AlertReason]) -> tuple[AlertReason, ...]:
    return tuple(reason for reason in AlertReason if reason in reasons)


def decide_alert(
    *,
    current_price: Decimal,
    current_at: datetime,
    evaluation: RoutePriceEvaluation,
    alert_price: Decimal | None,
    last_sent_alert: PriceObservation | None,
    policy: AlertPolicy,
) -> AlertResult:
    """Return one decision even when the observation satisfies several alert types."""

    if not isinstance(current_price, Decimal):
        raise TypeError("current_price must use Decimal")
    if current_price <= 0 or not current_price.is_finite():
        raise ValueError("current_price must be finite and greater than zero")
    if last_sent_alert is not None and last_sent_alert.observed_at > current_at:
        raise ValueError("last sent alert cannot be in the future")

    reasons: set[AlertReason] = set()
    statistically_eligible = evaluation.statistics.sample_size >= policy.min_score_samples
    if alert_price is not None and current_price <= alert_price:
        reasons.add(AlertReason.PRICE_TARGET)
    if (
        statistically_eligible
        and evaluation.statistics.recorded_low is not None
        and current_price < evaluation.statistics.recorded_low
    ):
        reasons.add(AlertReason.NEW_LOW)
    if (
        statistically_eligible
        and evaluation.deal_score.score is not None
        and evaluation.deal_score.score >= policy.exceptional_score
    ):
        reasons.add(AlertReason.EXCEPTIONAL_DEAL)

    drop_amount = None
    drop_percent = None
    if last_sent_alert is not None:
        drop_amount = last_sent_alert.price - current_price
        drop_percent = price_drop_percent(last_sent_alert.price, current_price)
        if drop_amount >= policy.min_drop_amount and drop_percent >= policy.min_drop_percent:
            reasons.add(AlertReason.SIGNIFICANT_DROP)

    if not reasons:
        return AlertResult(
            decision=AlertDecision.SUPPRESS,
            reasons=(AlertReason.NO_TRIGGER,),
            drop_amount=drop_amount,
            drop_percent=drop_percent,
        )

    independent_low_confidence_reasons = {
        AlertReason.PRICE_TARGET,
        AlertReason.NEW_LOW,
        AlertReason.SIGNIFICANT_DROP,
    }
    if (
        evaluation.statistics.confidence is ConfidenceLevel.LOW
        and AlertReason.EXCEPTIONAL_DEAL in reasons
        and not reasons.intersection(independent_low_confidence_reasons)
    ):
        reasons.add(AlertReason.LOW_CONFIDENCE_UNCORROBORATED)
        return AlertResult(
            decision=AlertDecision.SUPPRESS,
            reasons=_ordered_reasons(reasons),
            drop_amount=drop_amount,
            drop_percent=drop_percent,
        )

    if last_sent_alert is not None:
        cooldown_active = current_at - last_sent_alert.observed_at < timedelta(
            hours=policy.cooldown_hours
        )
        if cooldown_active and AlertReason.SIGNIFICANT_DROP not in reasons:
            reasons.add(AlertReason.COOLDOWN_ACTIVE)
            return AlertResult(
                decision=AlertDecision.SUPPRESS,
                reasons=_ordered_reasons(reasons),
                drop_amount=drop_amount,
                drop_percent=drop_percent,
            )

    return AlertResult(
        decision=AlertDecision.SEND,
        reasons=_ordered_reasons(reasons),
        drop_amount=drop_amount,
        drop_percent=drop_percent,
    )

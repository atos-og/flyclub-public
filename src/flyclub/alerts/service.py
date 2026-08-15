"""Persist, format, and deliver one idempotent consolidated alert decision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flyclub.alerts.engine import AlertDecision, AlertPolicy, AlertReason, AlertResult, decide_alert
from flyclub.alerts.formatter import format_alert_message
from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.models import FlightOption, OriginPriceComparison, PriceObservation, RouteDefinition


class AlertDeliveryStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AlertDecisionRecord:
    alert_id: UUID
    created: bool
    delivery_status: AlertDeliveryStatus


class AlertRepository(Protocol):
    def last_sent_alert_price(self, *, route_key: str) -> PriceObservation | None: ...

    def record_alert_decision(
        self,
        *,
        route_check_id: UUID,
        decision: AlertDecision,
        deal_score: int | None,
        reason_codes: tuple[str, ...],
        created_at: datetime,
    ) -> AlertDecisionRecord: ...

    def mark_alert_sent(
        self,
        *,
        alert_id: UUID,
        telegram_message_id: str,
        sent_at: datetime,
    ) -> None: ...

    def mark_alert_failed(self, *, alert_id: UUID, error_code: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AlertHandlingResult:
    alert: AlertResult
    delivered: bool


class AlertCoordinator:
    """Coordinate one alert without resending an existing route-check decision."""

    def __init__(
        self,
        repository: AlertRepository,
        telegram: TelegramClient,
        policy: AlertPolicy,
        *,
        positioning_context_min_savings: Decimal = Decimal("100"),
        formatter: Callable[..., str] = format_alert_message,
    ) -> None:
        if positioning_context_min_savings < 0:
            raise ValueError("positioning_context_min_savings must not be negative")
        self._repository = repository
        self._telegram = telegram
        self._policy = policy
        self._positioning_context_min_savings = positioning_context_min_savings
        self._formatter = formatter

    def handle(
        self,
        *,
        route: RouteDefinition,
        current_check_id: UUID,
        current_option: FlightOption,
        current_at: datetime,
        evaluation: RoutePriceEvaluation,
        origin_comparison: OriginPriceComparison | None = None,
    ) -> AlertHandlingResult:
        last_alert = self._repository.last_sent_alert_price(route_key=route.key)
        alert = decide_alert(
            current_price=current_option.price,
            current_at=current_at,
            evaluation=evaluation,
            alert_price=route.alert_price,
            last_sent_alert=last_alert,
            policy=self._policy,
        )
        actionable_comparison = origin_comparison
        if (
            alert.decision is AlertDecision.SEND
            and route.positioning_cost_estimate is not None
            and origin_comparison is not None
        ):
            gross_savings = origin_comparison.reference_price - current_option.price
            net_savings = gross_savings - route.positioning_cost_estimate
            if net_savings < self._positioning_context_min_savings:
                alert = AlertResult(
                    decision=AlertDecision.SUPPRESS,
                    reasons=(*alert.reasons, AlertReason.POSITIONING_COST_NOT_RECOVERED),
                    drop_amount=alert.drop_amount,
                    drop_percent=alert.drop_percent,
                )
        record = self._repository.record_alert_decision(
            route_check_id=current_check_id,
            decision=alert.decision,
            deal_score=evaluation.deal_score.score,
            reason_codes=tuple(reason.value for reason in alert.reasons),
            created_at=current_at,
        )
        if alert.decision is AlertDecision.SUPPRESS or not record.created:
            return AlertHandlingResult(alert=alert, delivered=False)

        if (
            actionable_comparison is not None
            and actionable_comparison.reference_price
            - current_option.price
            - (route.positioning_cost_estimate or Decimal("0"))
            < self._positioning_context_min_savings
        ):
            actionable_comparison = None
        message = self._formatter(
            route=route,
            option=current_option,
            evaluation=evaluation,
            alert=alert,
            origin_comparison=actionable_comparison,
        )
        try:
            delivery = self._telegram.send_message(message)
        except TelegramError as error:
            self._repository.mark_alert_failed(
                alert_id=record.alert_id,
                error_code=type(error).__name__,
            )
            raise
        self._repository.mark_alert_sent(
            alert_id=record.alert_id,
            telegram_message_id=delivery.message_id,
            sent_at=datetime.now(UTC),
        )
        return AlertHandlingResult(alert=alert, delivered=True)

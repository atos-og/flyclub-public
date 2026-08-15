from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from flyclub.alerts.engine import AlertDecision, AlertPolicy
from flyclub.alerts.service import (
    AlertCoordinator,
    AlertDecisionRecord,
    AlertDeliveryStatus,
)
from flyclub.alerts.telegram import TelegramDelivery, TelegramError
from flyclub.analysis.deal_score import DealClassification, DealScoreResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection
from flyclub.models import (
    CabinClass,
    FlightOption,
    MaxStops,
    OriginPriceComparison,
    OriginRole,
    RouteDefinition,
)

NOW = datetime(2027, 1, 1, tzinfo=UTC)


def _route(*, target: str | None) -> RouteDefinition:
    return RouteDefinition(
        key="route-key",
        origin_group="from_bh",
        origin_label="Belo Horizonte",
        origin_role=OriginRole.HOME,
        origin_airports=("CNF",),
        positioning_notice=None,
        destination="LIS",
        destination_name="Lisboa",
        departure_date=date(2027, 7, 1),
        return_date=date(2027, 7, 8),
        passengers=1,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ANY,
        alert_price=Decimal(target) if target is not None else None,
    )


def _evaluation() -> RoutePriceEvaluation:
    confidence = ConfidenceLevel.INSUFFICIENT
    return RoutePriceEvaluation(
        statistics=PriceStatistics(0, confidence, None, None, None, None, None),
        trend=TrendAnalysis(0, TrendDirection.INSUFFICIENT, None, None, None),
        recent_drop=None,
        deal_score=DealScoreResult(
            None,
            DealClassification.UNAVAILABLE,
            confidence,
            False,
            (),
        ),
    )


class FakeRepository:
    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.alert_id = uuid4()
        self.recorded: list[dict[str, object]] = []
        self.sent: list[dict[str, object]] = []
        self.failed: list[dict[str, object]] = []

    def last_sent_alert_price(self, *, route_key: str) -> None:
        assert route_key == "route-key"
        return None

    def record_alert_decision(self, **kwargs: object) -> AlertDecisionRecord:
        self.recorded.append(kwargs)
        decision = kwargs["decision"]
        status = (
            AlertDeliveryStatus.PENDING
            if decision is AlertDecision.SEND
            else AlertDeliveryStatus.NOT_REQUESTED
        )
        return AlertDecisionRecord(self.alert_id, self.created, status)

    def mark_alert_sent(self, **kwargs: object) -> None:
        self.sent.append(kwargs)

    def mark_alert_failed(self, **kwargs: object) -> None:
        self.failed.append(kwargs)


class FakeTelegram:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[str] = []

    def send_message(self, text: str) -> TelegramDelivery:
        self.messages.append(text)
        if self.fail:
            raise TelegramError("sanitized")
        return TelegramDelivery("message-123")


def _handle(
    repository: FakeRepository,
    telegram: FakeTelegram,
    *,
    target: str | None,
) -> object:
    coordinator = AlertCoordinator(
        repository,  # type: ignore[arg-type]
        telegram,  # type: ignore[arg-type]
        AlertPolicy(),
        formatter=lambda **_kwargs: "formatted alert",
    )
    return coordinator.handle(
        route=_route(target=target),
        current_check_id=uuid4(),
        current_option=FlightOption(Decimal("80"), "BRL", ()),
        current_at=NOW,
        evaluation=_evaluation(),
    )


def test_suppressed_decision_is_persisted_without_telegram() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()

    result = _handle(repository, telegram, target=None)

    assert result.alert.decision is AlertDecision.SUPPRESS
    assert result.delivered is False
    assert repository.recorded[0]["deal_score"] is None
    assert repository.sent == []
    assert telegram.messages == []


def test_send_decision_is_delivered_and_marked_sent() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()

    result = _handle(repository, telegram, target="100")

    assert result.alert.decision is AlertDecision.SEND
    assert result.delivered is True
    assert telegram.messages == ["formatted alert"]
    assert repository.sent[0]["telegram_message_id"] == "message-123"
    assert repository.failed == []


def test_existing_decision_is_never_sent_twice() -> None:
    repository = FakeRepository(created=False)
    telegram = FakeTelegram()

    result = _handle(repository, telegram, target="100")

    assert result.delivered is False
    assert telegram.messages == []


def test_delivery_failure_is_marked_and_propagated() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram(fail=True)

    with pytest.raises(TelegramError, match="sanitized"):
        _handle(repository, telegram, target="100")

    assert repository.failed[0]["alert_id"] == repository.alert_id
    assert repository.failed[0]["error_code"] == "TelegramError"
    assert repository.sent == []


def test_positioning_context_is_forwarded_only_for_material_savings() -> None:
    captured: list[dict[str, object]] = []
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = AlertCoordinator(
        repository,  # type: ignore[arg-type]
        telegram,  # type: ignore[arg-type]
        AlertPolicy(),
        positioning_context_min_savings=Decimal("100"),
        formatter=lambda **kwargs: captured.append(kwargs) or "formatted alert",
    )
    common = {
        "route": _route(target="100"),
        "current_option": FlightOption(Decimal("80"), "BRL", ()),
        "current_at": NOW,
        "evaluation": _evaluation(),
    }

    coordinator.handle(
        current_check_id=uuid4(),
        origin_comparison=OriginPriceComparison("CNF", Decimal("179")),
        **common,
    )
    assert captured[0]["origin_comparison"] is None

    coordinator.handle(
        current_check_id=uuid4(),
        origin_comparison=OriginPriceComparison("CNF", Decimal("180")),
        **common,
    )
    assert captured[1]["origin_comparison"] == OriginPriceComparison("CNF", Decimal("180"))

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from flyclub.alerts.telegram import TelegramDelivery, TelegramError
from flyclub.analysis.deal_score import DealClassification, DealScoreResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection
from flyclub.flexible_market_alerts import (
    FlexibleAlertPolicy,
    FlexibleAlertReason,
    FlexibleMarketAlertCoordinator,
    decide_flexible_alert,
    format_flexible_market_alert,
)
from flyclub.flexible_market_models import (
    CalendarFare,
    FlexibleMarketDefinition,
    FlexibleMarketPeriod,
)
from flyclub.models import CabinClass, FlightLeg, FlightOption, MaxStops
from flyclub.storage.flexible_market import (
    FlexibleAlertRecord,
    FlexibleDecision,
    FlexibleDeliveryStatus,
    LastFlexibleAlert,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _evaluation(score: int | None, *, samples: int = 12) -> RoutePriceEvaluation:
    confidence = ConfidenceLevel.LOW if samples >= 12 else ConfidenceLevel.INSUFFICIENT
    return RoutePriceEvaluation(
        statistics=PriceStatistics(
            sample_size=samples,
            confidence=confidence,
            p10=Decimal("800") if samples else None,
            p50=Decimal("1000") if samples else None,
            p90=Decimal("1200") if samples else None,
            percentile_rank=Decimal("5") if samples else None,
            recorded_low=Decimal("780") if samples else None,
        ),
        trend=TrendAnalysis(
            sample_size=samples,
            direction=TrendDirection.STABLE,
            change_percent=Decimal("0"),
            previous_median=Decimal("1000"),
            recent_median=Decimal("1000"),
        ),
        recent_drop=None,
        deal_score=DealScoreResult(
            score=score,
            classification=(
                DealClassification.UNAVAILABLE if score is None else DealClassification.GREAT
            ),
            confidence=confidence,
            provisional=confidence is ConfidenceLevel.LOW,
            components=(),
        ),
    )


def _decide(
    score: int | None,
    *,
    threshold: int,
    samples: int = 12,
    last: LastFlexibleAlert | None = None,
) -> object:
    return decide_flexible_alert(
        current_price=Decimal("750"),
        current_at=NOW,
        departure_date=date(2026, 11, 10),
        arrival_airport="LHR",
        evaluation=_evaluation(score, samples=samples),
        minimum_deal_score=threshold,
        last_alert=last,
        policy=FlexibleAlertPolicy(),
    )


def test_current_year_requires_the_stricter_80_point_floor() -> None:
    assert _decide(79, threshold=80).decision is FlexibleDecision.SUPPRESS
    assert _decide(80, threshold=80).decision is FlexibleDecision.SEND


def test_future_period_accepts_great_deals_from_75() -> None:
    result = _decide(75, threshold=75)

    assert result.decision is FlexibleDecision.SEND
    assert result.reasons == (FlexibleAlertReason.QUALIFIED_SCORE,)


def test_score_never_bypasses_twelve_prior_observations() -> None:
    result = _decide(None, threshold=75, samples=11)

    assert result.decision is FlexibleDecision.SUPPRESS
    assert result.reasons == (FlexibleAlertReason.INSUFFICIENT_HISTORY,)


def test_same_offer_is_not_repeated_after_cooldown_without_a_real_drop() -> None:
    last = LastFlexibleAlert(
        price=Decimal("750"),
        observed_at=NOW - timedelta(hours=30),
        departure_date=date(2026, 11, 10),
        arrival_airport="LHR",
    )

    result = _decide(85, threshold=80, last=last)

    assert result.decision is FlexibleDecision.SUPPRESS
    assert FlexibleAlertReason.UNCHANGED_OFFER in result.reasons


def test_significant_price_drop_can_bypass_cooldown() -> None:
    last = LastFlexibleAlert(
        price=Decimal("900"),
        observed_at=NOW - timedelta(hours=2),
        departure_date=date(2026, 11, 10),
        arrival_airport="LHR",
    )

    result = _decide(85, threshold=80, last=last)

    assert result.decision is FlexibleDecision.SEND
    assert FlexibleAlertReason.SIGNIFICANT_DROP in result.reasons


def _market() -> FlexibleMarketDefinition:
    return FlexibleMarketDefinition(
        key="sample_market",
        label="Sample market",
        origin_airports=("JFK",),
        destination_airports=("LHR", "LGW"),
        trip_duration_days=10,
        passengers=1,
        cabin=CabinClass.ECONOMY,
        currency="USD",
        max_stops=MaxStops.ANY,
        minimum_days_ahead=14,
        maximum_days_ahead=305,
        score_threshold_2026=80,
        score_threshold_future=75,
    )


def _period() -> FlexibleMarketPeriod:
    return FlexibleMarketPeriod(
        key="remaining_2026",
        label="current period",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 12, 31),
        minimum_deal_score=80,
    )


def _option() -> FlightOption:
    return FlightOption(
        price=Decimal("750"),
        currency="USD",
        stops=1,
        duration_minutes=700,
        google_flights_url="https://www.google.com/travel/flights/booking?tfs=sample&x=1",
        legs=(
            FlightLeg(0, "JFK", "LHR", None, None, "BA", "117"),
            FlightLeg(1, "LHR", "JFK", None, None, "BA", "118"),
        ),
    )


def test_flexible_alert_message_is_compact_verified_and_hides_the_long_url() -> None:
    message = format_flexible_market_alert(
        market=_market(),
        period=_period(),
        fare=CalendarFare(date(2026, 11, 10), date(2026, 11, 20), Decimal("740"), "USD"),
        option=_option(),
        evaluation=_evaluation(85),
        result=decide_flexible_alert(
            current_price=Decimal("750"),
            current_at=NOW,
            departure_date=date(2026, 11, 10),
            arrival_airport="LHR",
            evaluation=_evaluation(85),
            minimum_deal_score=80,
            last_alert=None,
            policy=FlexibleAlertPolicy(),
        ),
    )

    assert "GARIMPO FLEXÍVEL · 85/100" in message
    assert "10/11/2026 a 20/11/2026 · 10 dias" in message
    assert "Corte deste período: 80/100" in message
    assert "tarifa confirmada" in message
    assert ">Ver oferta</a>" in message
    assert "Ver oferta: https" not in message


class FakeAlertRepository:
    def __init__(self) -> None:
        self.sent: tuple[object, ...] | None = None
        self.decision: dict[str, object] | None = None

    def last_sent_alert(self, **_kwargs: object) -> None:
        return None

    def record_alert_decision(self, **kwargs: object) -> FlexibleAlertRecord:
        self.decision = kwargs
        return FlexibleAlertRecord(uuid4(), True, FlexibleDeliveryStatus.PENDING)

    def mark_alert_sent(self, **kwargs: object) -> None:
        self.sent = tuple(kwargs.values())

    def mark_alert_failed(self, **_kwargs: object) -> None:
        raise AssertionError("delivery should not fail")


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    def send_message(self, text: str, *, parse_mode: str | None = None) -> TelegramDelivery:
        self.messages.append((text, parse_mode))
        return TelegramDelivery("321")


def test_coordinator_persists_and_delivers_one_qualified_alert() -> None:
    repository = FakeAlertRepository()
    telegram = FakeTelegram()
    coordinator = FlexibleMarketAlertCoordinator(repository, telegram, FlexibleAlertPolicy())

    delivered = coordinator.handle(
        check_id=uuid4(),
        market=_market(),
        period=_period(),
        fare=CalendarFare(date(2026, 11, 10), date(2026, 11, 20), Decimal("740"), "USD"),
        option=_option(),
        current_at=NOW,
        evaluation=_evaluation(85),
    )

    assert delivered is True
    assert repository.decision["decision"] is FlexibleDecision.SEND
    assert repository.sent is not None
    assert telegram.messages[0][1] == "HTML"


def test_coordinator_records_suppression_without_calling_telegram() -> None:
    repository = FakeAlertRepository()
    telegram = FakeTelegram()
    coordinator = FlexibleMarketAlertCoordinator(repository, telegram, FlexibleAlertPolicy())

    delivered = coordinator.handle(
        check_id=uuid4(),
        market=_market(),
        period=_period(),
        fare=CalendarFare(date(2026, 11, 10), date(2026, 11, 20), Decimal("740"), "USD"),
        option=_option(),
        current_at=NOW,
        evaluation=_evaluation(70),
    )

    assert delivered is False
    assert repository.decision["decision"] is FlexibleDecision.SUPPRESS
    assert telegram.messages == []


def test_coordinator_marks_failed_telegram_delivery() -> None:
    class FailingRepository(FakeAlertRepository):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def mark_alert_failed(self, **_kwargs: object) -> None:
            self.failed = True

    class FailingTelegram:
        def send_message(self, *_args, **_kwargs) -> object:
            raise TelegramError("sanitized")

    repository = FailingRepository()
    coordinator = FlexibleMarketAlertCoordinator(
        repository, FailingTelegram(), FlexibleAlertPolicy()
    )

    import pytest

    with pytest.raises(TelegramError):
        coordinator.handle(
            check_id=uuid4(),
            market=_market(),
            period=_period(),
            fare=CalendarFare(date(2026, 11, 10), date(2026, 11, 20), Decimal("740"), "USD"),
            option=_option(),
            current_at=NOW,
            evaluation=_evaluation(85),
        )

    assert repository.failed is True

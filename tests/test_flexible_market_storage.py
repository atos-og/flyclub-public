from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from flyclub.flexible_market_models import (
    CalendarFare,
    FlexibleMarketDefinition,
    FlexibleMarketPeriod,
)
from flyclub.models import (
    CabinClass,
    FlightLeg,
    FlightOption,
    MaxStops,
    SearchOutcome,
    SearchStatus,
)
from flyclub.storage.flexible_market import (
    FlexibleDecision,
    FlexibleDeliveryStatus,
    FlexibleMarketRepository,
)
from flyclub.storage.postgres import StorageError


class FakeCursor:
    def __init__(
        self,
        *,
        history: list[tuple[Any, ...]] | None = None,
        last_alert: tuple[Any, ...] | None = None,
        duplicate_check_id: object | None = None,
        duplicate_alert: tuple[Any, ...] | None = None,
    ) -> None:
        self.executions: list[tuple[str, Any]] = []
        self._result: tuple[Any, ...] | None = None
        self.history = history or []
        self.last_alert = last_alert
        self.duplicate_check_id = duplicate_check_id
        self.duplicate_alert = duplicate_alert
        self.rowcount = 1

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        normalized = " ".join(query.split())
        self.executions.append((normalized, params))
        if normalized.startswith("INSERT INTO flexible_market_checks"):
            self._result = None if self.duplicate_check_id else (params[0],)
        elif normalized.startswith("SELECT id FROM flexible_market_checks"):
            self._result = (self.duplicate_check_id,) if self.duplicate_check_id else None
        elif normalized.startswith("SELECT check_row.best_price"):
            self._result = self.last_alert
        elif normalized.startswith("INSERT INTO flexible_market_alert_history"):
            self._result = None if self.duplicate_alert else (params[0], params[8])
        elif normalized.startswith("SELECT id, delivery_status"):
            self._result = self.duplicate_alert
        else:
            self._result = None

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.history


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_value = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_value


def _repository(cursor: FakeCursor) -> FlexibleMarketRepository:
    return FlexibleMarketRepository(
        "postgresql://test.invalid/flyclub", connect=lambda _url: FakeConnection(cursor)
    )


def _market() -> FlexibleMarketDefinition:
    return FlexibleMarketDefinition(
        "sample_market",
        "Sample market",
        ("JFK",),
        ("LHR", "LGW"),
        10,
        1,
        CabinClass.ECONOMY,
        "USD",
        MaxStops.ANY,
        14,
        305,
        80,
        75,
    )


def _period() -> FlexibleMarketPeriod:
    return FlexibleMarketPeriod("from_2027", "future", date(2027, 1, 1), date(2027, 6, 1), 75)


def _option() -> FlightOption:
    return FlightOption(
        Decimal("850.25"),
        "USD",
        (FlightLeg(0, "JFK", "LHR", None, None, "BA", "117"),),
        stops=0,
        duration_minutes=600,
        google_flights_url="https://www.google.com/travel/flights/booking?tfs=sample",
    )


def test_successful_check_persists_decimal_verified_itinerary_and_private_market_arrays() -> None:
    cursor = FakeCursor()
    repository = _repository(cursor)
    option = _option()
    check_id = repository.record_check(
        run_id=uuid4(),
        market=_market(),
        period=_period(),
        outcome=SearchOutcome("fake", SearchStatus.SUCCESS, (option,)),
        calendar_fare=CalendarFare(date(2027, 1, 10), date(2027, 1, 20), Decimal("840.10"), "USD"),
        provider_requests=6,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    query, params = cursor.executions[0]
    assert query.startswith("INSERT INTO flexible_market_checks")
    assert params[0] == check_id
    assert params[11] == ["JFK"]
    assert params[12] == ["LGW", "LHR"]
    assert params[21] == Decimal("840.10")
    assert params[22] == Decimal("850.25")
    assert params[29] is not None


def test_history_is_prior_only_and_returned_chronologically() -> None:
    older = datetime(2026, 9, 1, tzinfo=UTC)
    newer = datetime(2026, 9, 2, tzinfo=UTC)
    cursor = FakeCursor(history=[(Decimal("900"), newer), (Decimal("950"), older)])
    check_id = uuid4()

    history = _repository(cursor).price_history(
        market_key="sample_market",
        period_key="from_2027",
        exclude_check_id=check_id,
        limit=25,
    )

    assert [item.price for item in history] == [Decimal("950"), Decimal("900")]
    assert cursor.executions[0][1] == ("sample_market", "from_2027", check_id, 25)


def test_alert_decision_and_delivery_are_isolated_from_regular_alert_history() -> None:
    cursor = FakeCursor()
    repository = _repository(cursor)
    created_at = datetime(2026, 9, 1, tzinfo=UTC)

    record = repository.record_alert_decision(
        check_id=uuid4(),
        market_key="sample_market",
        period_key="from_2027",
        decision=FlexibleDecision.SEND,
        deal_score=81,
        reason_codes=("QUALIFIED_SCORE",),
        created_at=created_at,
    )
    repository.mark_alert_sent(alert_id=record.alert_id, telegram_message_id="321")

    assert record.delivery_status is FlexibleDeliveryStatus.PENDING
    assert any(
        query.startswith("INSERT INTO flexible_market_alert_history")
        for query, _params in cursor.executions
    )
    assert not any(query.startswith("INSERT INTO alert_history") for query, _ in cursor.executions)
    assert any(
        query.startswith("UPDATE flexible_market_alert_history")
        for query, _params in cursor.executions
    )


def test_empty_check_has_no_invented_dates_prices_or_itinerary() -> None:
    cursor = FakeCursor()

    _repository(cursor).record_check(
        run_id=uuid4(),
        market=_market(),
        period=_period(),
        outcome=SearchOutcome("fake", SearchStatus.EMPTY),
        calendar_fare=None,
        provider_requests=5,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    params = cursor.executions[0][1]
    assert params[18:23] == (None, None, None, None, None)
    assert params[24] == 0
    assert params[29] is None
    assert params[30] is None


def test_duplicate_check_and_alert_return_existing_records() -> None:
    existing_check = uuid4()
    cursor = FakeCursor(duplicate_check_id=existing_check)
    repository = _repository(cursor)

    resolved = repository.record_check(
        run_id=uuid4(),
        market=_market(),
        period=_period(),
        outcome=SearchOutcome("fake", SearchStatus.EMPTY),
        calendar_fare=None,
        provider_requests=5,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert resolved == existing_check

    existing_alert = uuid4()
    alert_cursor = FakeCursor(duplicate_alert=(existing_alert, "SENT"))
    alert = _repository(alert_cursor).record_alert_decision(
        check_id=existing_check,
        market_key="sample_market",
        period_key="from_2027",
        decision=FlexibleDecision.SEND,
        deal_score=81,
        reason_codes=("QUALIFIED_SCORE",),
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert alert.alert_id == existing_alert
    assert alert.created is False
    assert alert.delivery_status is FlexibleDeliveryStatus.SENT


def test_last_sent_alert_and_evaluation_update_are_explicit() -> None:
    sent_at = datetime(2026, 9, 1, tzinfo=UTC)
    cursor = FakeCursor(last_alert=(Decimal("850.25"), sent_at, date(2027, 1, 10), "LHR"))
    repository = _repository(cursor)
    alert = repository.last_sent_alert(market_key="sample_market", period_key="from_2027")

    assert alert is not None
    assert alert.price == Decimal("850.25")
    assert alert.departure_date == date(2027, 1, 10)

    from flyclub.analysis.deal_score import DealClassification, DealScoreResult
    from flyclub.analysis.evaluator import RoutePriceEvaluation
    from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
    from flyclub.analysis.trend import TrendAnalysis, TrendDirection

    evaluation = RoutePriceEvaluation(
        PriceStatistics(
            12,
            ConfidenceLevel.LOW,
            Decimal("800"),
            Decimal("900"),
            Decimal("1000"),
            Decimal("5"),
            Decimal("790"),
        ),
        TrendAnalysis(8, TrendDirection.STABLE, Decimal("0"), Decimal("900"), Decimal("900")),
        None,
        DealScoreResult(81, DealClassification.GREAT, ConfidenceLevel.LOW, True, ()),
    )
    repository.update_evaluation(check_id=uuid4(), evaluation=evaluation)

    update = next(
        params
        for query, params in cursor.executions
        if query.startswith("UPDATE flexible_market_checks")
    )
    assert update[:5] == (12, "LOW", 81, "GREAT", True)


def test_repository_rejects_non_postgres_urls_and_mismatched_success_payloads() -> None:
    with pytest.raises(StorageError, match="PostgreSQL"):
        FlexibleMarketRepository("sqlite:///private.db")

    repository = _repository(FakeCursor())
    with pytest.raises(ValueError, match="calendar and verified"):
        repository.record_check(
            run_id=uuid4(),
            market=_market(),
            period=_period(),
            outcome=SearchOutcome("fake", SearchStatus.SUCCESS, (_option(),)),
            calendar_fare=None,
            provider_requests=1,
            checked_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

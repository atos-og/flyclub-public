from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from flyclub.alerts.telegram import TelegramDelivery, TelegramError
from flyclub.daily_summary import (
    DailyPriceSnapshot,
    DailySummaryClaim,
    DailySummaryDeliveryStatus,
    format_daily_summary_message,
    send_daily_summary,
)
from flyclub.models import CabinClass, MaxStops, OriginRole, RouteDefinition


def _route(
    origin_group: str,
    origin_label: str,
    destination: str,
    destination_name: str,
) -> RouteDefinition:
    return RouteDefinition(
        key=f"{origin_group}-{destination}-summary",
        origin_group=origin_group,
        origin_label=origin_label,
        origin_role=(OriginRole.HOME if origin_group == "from_bh" else OriginRole.POSITIONING),
        origin_airports=("CNF",) if origin_group == "from_bh" else ("GRU",),
        positioning_notice=(None if origin_group == "from_bh" else "Positioning required"),
        destination=destination,
        destination_name=destination_name,
        departure_date=date(2027, 3, 10),
        return_date=date(2027, 3, 17),
        passengers=1,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ANY,
        alert_price=None,
    )


def _routes() -> tuple[RouteDefinition, ...]:
    return (
        _route("from_bh", "Belo Horizonte", "SCL", "Santiago"),
        _route("from_bh", "Belo Horizonte", "AEP", "Buenos Aires"),
        _route("from_sp", "São Paulo", "SCL", "Santiago"),
    )


def _snapshots() -> tuple[DailyPriceSnapshot, ...]:
    routes = _routes()
    return (
        DailyPriceSnapshot(
            routes[0].key,
            Decimal("1900"),
            Decimal("2000"),
            datetime(2027, 3, 11, 10, tzinfo=UTC),
        ),
        DailyPriceSnapshot(
            routes[1].key,
            Decimal("2100"),
            Decimal("2100"),
            datetime(2027, 3, 11, 10, tzinfo=UTC),
        ),
        DailyPriceSnapshot(routes[2].key, None, Decimal("1800"), None),
    )


def test_daily_summary_is_compact_informational_and_grouped() -> None:
    message = format_daily_summary_message(
        routes=_routes(),
        snapshots=_snapshots(),
        summary_date=date(2027, 3, 11),
    )

    assert message.startswith("☀️ RESUMO DIÁRIO · 11/03")
    assert "Ida e volta · 10/03 a 17/03 · 1 passageiro" in message
    assert "Belo Horizonte\n• Santiago: R$ 1.900,00 · ↓ R$ 100,00 (5,0%)" in message
    assert "• Buenos Aires: R$ 2.100,00 · estável" in message
    assert "São Paulo\n• Santiago: sem preço encontrado hoje" in message
    assert "alertas de oportunidade continuam usando critérios próprios" in message
    assert "OPORTUNIDADE EXCEPCIONAL" not in message


def test_daily_summary_formats_non_brl_increase_and_plural_passengers() -> None:
    route = replace(
        _routes()[0],
        currency="USD",
        passengers=2,
    )
    snapshot = DailyPriceSnapshot(
        route.key,
        Decimal("1500"),
        Decimal("1200"),
        datetime(2027, 3, 11, 10, tzinfo=UTC),
    )

    message = format_daily_summary_message(
        routes=(route,),
        snapshots=(snapshot,),
        summary_date=date(2027, 3, 11),
    )

    assert "2 passageiros" in message
    assert "USD 1500.00 · ↑ USD 300.00 (25,0%)" in message


def test_daily_summary_omits_change_without_previous_price() -> None:
    route = _routes()[0]
    snapshot = DailyPriceSnapshot(route.key, Decimal("1900"), None, None)

    message = format_daily_summary_message(
        routes=(route,),
        snapshots=(snapshot,),
        summary_date=date(2027, 3, 11),
    )

    assert "Santiago: R$ 1.900,00\n" in message


def test_daily_summary_rejects_empty_routes_and_oversized_message() -> None:
    with pytest.raises(ValueError, match="at least one route"):
        format_daily_summary_message(routes=(), snapshots=(), summary_date=date(2027, 3, 11))

    oversized = replace(_routes()[0], destination_name="X" * 4096)
    with pytest.raises(ValueError, match="message limit"):
        format_daily_summary_message(
            routes=(oversized,),
            snapshots=(),
            summary_date=date(2027, 3, 11),
        )


class FakeRepository:
    def __init__(self, *, claimed: bool = True) -> None:
        self.snapshots = _snapshots()
        self.claim = DailySummaryClaim(
            uuid4(),
            claimed,
            DailySummaryDeliveryStatus.PENDING if claimed else DailySummaryDeliveryStatus.SENT,
        )
        self.price_query: tuple[tuple[str, ...], datetime, datetime] | None = None
        self.claimed_date: date | None = None
        self.sent: tuple[UUID, str] | None = None
        self.failed: tuple[UUID, str] | None = None

    def latest_daily_prices(
        self,
        *,
        route_keys: tuple[str, ...],
        observed_from: datetime,
        observed_until: datetime,
    ) -> tuple[DailyPriceSnapshot, ...]:
        self.price_query = (route_keys, observed_from, observed_until)
        return self.snapshots

    def claim_daily_summary(
        self,
        *,
        summary_date: date,
        claimed_at: datetime,
    ) -> DailySummaryClaim:
        assert claimed_at.tzinfo is not None
        self.claimed_date = summary_date
        return self.claim

    def mark_daily_summary_sent(
        self,
        *,
        summary_id: UUID,
        telegram_message_id: str,
        sent_at: datetime,
    ) -> None:
        assert sent_at.tzinfo is not None
        self.sent = (summary_id, telegram_message_id)

    def mark_daily_summary_failed(self, *, summary_id: UUID, error_code: str) -> None:
        self.failed = (summary_id, error_code)


class FakeTelegram:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[str] = []

    def send_message(self, text: str) -> TelegramDelivery:
        self.messages.append(text)
        if self.fail:
            raise TelegramError("sanitized failure")
        return TelegramDelivery("daily-123")


def test_daily_summary_sends_once_using_brasilia_day_bounds() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()

    result = send_daily_summary(
        routes=_routes(),
        repository=repository,
        telegram=telegram,  # type: ignore[arg-type]
        now=datetime(2027, 3, 11, 11, 23, tzinfo=UTC),
    )

    assert result.delivered is True
    assert result.summary_date == date(2027, 3, 11)
    assert result.available_routes == 2
    assert len(telegram.messages) == 1
    assert repository.price_query is not None
    assert repository.price_query[1] == datetime(2027, 3, 11, 3, tzinfo=UTC)
    assert repository.price_query[2] == datetime(2027, 3, 11, 11, 23, tzinfo=UTC)
    assert repository.claimed_date == date(2027, 3, 11)
    assert repository.sent == (repository.claim.summary_id, "daily-123")


def test_existing_daily_summary_is_not_sent_again() -> None:
    repository = FakeRepository(claimed=False)
    telegram = FakeTelegram()

    result = send_daily_summary(
        routes=_routes(),
        repository=repository,
        telegram=telegram,  # type: ignore[arg-type]
        now=datetime(2027, 3, 11, 12, tzinfo=UTC),
    )

    assert result.delivered is False
    assert telegram.messages == []
    assert repository.sent is None


def test_failed_daily_summary_records_sanitized_failure() -> None:
    repository = FakeRepository()

    with pytest.raises(TelegramError, match="sanitized"):
        send_daily_summary(
            routes=_routes(),
            repository=repository,
            telegram=FakeTelegram(fail=True),  # type: ignore[arg-type]
            now=datetime(2027, 3, 11, 12, tzinfo=UTC),
        )

    assert repository.failed == (repository.claim.summary_id, "TelegramError")


def test_daily_summary_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        send_daily_summary(
            routes=_routes(),
            repository=FakeRepository(),
            telegram=FakeTelegram(),  # type: ignore[arg-type]
            now=datetime(2027, 3, 11),
        )

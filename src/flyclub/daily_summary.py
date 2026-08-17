"""One daily informational price summary, isolated from opportunity alerts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.config import ConfigError, load_config
from flyclub.models import RouteDefinition
from flyclub.route_planner import plan_routes

SUMMARY_TIMEZONE = ZoneInfo("America/Sao_Paulo")


class DailySummaryDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DailyPriceSnapshot:
    route_key: str
    current_price: Decimal | None
    previous_price: Decimal | None
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DailySummaryClaim:
    summary_id: UUID
    claimed: bool
    delivery_status: DailySummaryDeliveryStatus


@dataclass(frozen=True, slots=True)
class DailySummaryResult:
    summary_date: date
    delivered: bool
    available_routes: int


class DailySummaryRepository(Protocol):
    def latest_daily_prices(
        self,
        *,
        route_keys: tuple[str, ...],
        observed_from: datetime,
        observed_until: datetime,
    ) -> tuple[DailyPriceSnapshot, ...]: ...

    def claim_daily_summary(
        self,
        *,
        summary_date: date,
        claimed_at: datetime,
    ) -> DailySummaryClaim: ...

    def mark_daily_summary_sent(
        self,
        *,
        summary_id: UUID,
        telegram_message_id: str,
        sent_at: datetime,
    ) -> None: ...

    def mark_daily_summary_failed(self, *, summary_id: UUID, error_code: str) -> None: ...


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {formatted}"
    return f"{currency} {value:.2f}"


def _passenger_label(passengers: int) -> str:
    return f"{passengers} passageiro" if passengers == 1 else f"{passengers} passageiros"


def _change_label(snapshot: DailyPriceSnapshot, currency: str) -> str:
    current = snapshot.current_price
    previous = snapshot.previous_price
    if current is None or previous is None:
        return ""
    difference = previous - current
    if difference == 0:
        return " · estável"
    percentage = abs(difference) * Decimal("100") / previous
    direction = "↓" if difference > 0 else "↑"
    formatted_percent = f"{percentage.quantize(Decimal('0.1')):.1f}".replace(".", ",")
    return f" · {direction} {_money(abs(difference), currency)} ({formatted_percent}%)"


def format_daily_summary_message(
    *,
    routes: tuple[RouteDefinition, ...],
    snapshots: tuple[DailyPriceSnapshot, ...],
    summary_date: date,
) -> str:
    if not routes:
        raise ValueError("Daily summary requires at least one route")
    by_key = {snapshot.route_key: snapshot for snapshot in snapshots}
    first_route = routes[0]
    lines = [
        f"☀️ RESUMO DIÁRIO · {summary_date:%d/%m}",
        "",
        f"✈️ Ida e volta · {first_route.departure_date:%d/%m} a "
        f"{first_route.return_date:%d/%m} · {_passenger_label(first_route.passengers)}",
    ]

    current_origin: str | None = None
    for route in routes:
        if route.origin_label != current_origin:
            lines.extend(("", route.origin_label))
            current_origin = route.origin_label
        snapshot = by_key.get(route.key)
        destination = route.destination_name or route.destination
        if snapshot is None or snapshot.current_price is None:
            lines.append(f"• {destination}: sem preço encontrado hoje")
            continue
        lines.append(
            f"• {destination}: {_money(snapshot.current_price, route.currency)}"
            f"{_change_label(snapshot, route.currency)}"
        )

    lines.extend(
        (
            "",
            "Resumo informativo. Os alertas de oportunidade continuam usando critérios próprios.",
        )
    )
    message = "\n".join(lines)
    if len(message) > 4096:
        raise ValueError("Daily summary exceeds Telegram's message limit")
    return message


def _daily_window(now: datetime) -> tuple[date, datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("Daily summary time must include a timezone")
    local_now = now.astimezone(SUMMARY_TIMEZONE)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=SUMMARY_TIMEZONE)
    return local_now.date(), local_start.astimezone(UTC), now.astimezone(UTC)


def send_daily_summary(
    *,
    routes: tuple[RouteDefinition, ...],
    repository: DailySummaryRepository,
    telegram: TelegramClient,
    now: datetime | None = None,
) -> DailySummaryResult:
    selected_now = now or datetime.now(UTC)
    summary_date, observed_from, observed_until = _daily_window(selected_now)
    snapshots = repository.latest_daily_prices(
        route_keys=tuple(route.key for route in routes),
        observed_from=observed_from,
        observed_until=observed_until,
    )
    message = format_daily_summary_message(
        routes=routes,
        snapshots=snapshots,
        summary_date=summary_date,
    )
    claim = repository.claim_daily_summary(
        summary_date=summary_date,
        claimed_at=selected_now.astimezone(UTC),
    )
    available_routes = sum(snapshot.current_price is not None for snapshot in snapshots)
    if not claim.claimed:
        return DailySummaryResult(summary_date, False, available_routes)

    try:
        delivery = telegram.send_message(message)
    except TelegramError as error:
        repository.mark_daily_summary_failed(
            summary_id=claim.summary_id,
            error_code=type(error).__name__,
        )
        raise
    repository.mark_daily_summary_sent(
        summary_id=claim.summary_id,
        telegram_message_id=delivery.message_id,
        sent_at=datetime.now(UTC),
    )
    return DailySummaryResult(summary_date, True, available_routes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flyclub-daily-summary",
        description="Send one idempotent daily summary from persisted prices",
    )
    parser.add_argument("--config", help="Path to an ignored local routes YAML file")
    return parser


def cli(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    load_dotenv(override=False)
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        routes = plan_routes(config)
        from flyclub.storage.postgres import PostgresRepository, StorageError

        result = send_daily_summary(
            routes=routes,
            repository=PostgresRepository.from_env(),
            telegram=TelegramClient.from_env(),
            now=clock(),
        )
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except (StorageError, TelegramError, ValueError) as error:
        print(f"Daily summary error: {error}", file=sys.stderr)
        return 1

    state = "sent" if result.delivered else "already handled"
    print(f"Daily price summary {state}: {result.available_routes} route prices available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from flyclub.daily_summary import DailySummaryDeliveryStatus
from flyclub.storage.postgres import PostgresRepository, StorageError


class DailyCursor:
    def __init__(
        self,
        *,
        price_rows: list[tuple[Any, ...]] | None = None,
        claim_row: tuple[Any, ...] | None = None,
        existing_row: tuple[Any, ...] | None = None,
        update_count: int = 1,
    ) -> None:
        self.price_rows = price_rows or []
        self.claim_row = claim_row
        self.existing_row = existing_row
        self.rowcount = update_count
        self.executions: list[tuple[str, Any]] = []
        self._one: tuple[Any, ...] | None = None
        self._many: list[tuple[Any, ...]] = []

    def __enter__(self) -> DailyCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: Any = None, **_kwargs: Any) -> None:
        normalized = " ".join(query.split())
        self.executions.append((normalized, params))
        self._one = None
        self._many = []
        if normalized.startswith("WITH requested_routes"):
            self._many = self.price_rows
        elif normalized.startswith("INSERT INTO daily_summary_history"):
            self._one = self.claim_row
        elif normalized.startswith("SELECT id, delivery_status FROM daily_summary_history"):
            self._one = self.existing_row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._one

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._many


class DailyConnection:
    def __init__(self, cursor: DailyCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> DailyConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> DailyCursor:
        return self._cursor


def _repository(cursor: DailyCursor) -> PostgresRepository:
    return PostgresRepository(
        "postgresql://test.invalid/flyclub",
        connect=lambda _database_url: DailyConnection(cursor),
    )


def test_latest_daily_prices_preserves_requested_order_and_bounds() -> None:
    observed = datetime(2027, 3, 11, 10, tzinfo=UTC)
    cursor = DailyCursor(
        price_rows=[
            ("route-a", Decimal("1900"), Decimal("2000"), observed),
            ("route-b", None, Decimal("1700"), None),
        ]
    )
    start = datetime(2027, 3, 11, 3, tzinfo=UTC)
    end = datetime(2027, 3, 11, 11, 23, tzinfo=UTC)

    prices = _repository(cursor).latest_daily_prices(
        route_keys=("route-a", "route-b"),
        observed_from=start,
        observed_until=end,
    )

    assert prices[0].current_price == Decimal("1900")
    assert prices[0].previous_price == Decimal("2000")
    assert prices[1].current_price is None
    query, params = cursor.executions[0]
    assert query.startswith("WITH requested_routes")
    assert params == (["route-a", "route-b"], start, end, start, ["route-a", "route-b"])


def test_daily_summary_claim_is_new_or_existing() -> None:
    summary_id = uuid4()
    claimed_at = datetime(2027, 3, 11, 11, 23, tzinfo=UTC)
    created = _repository(DailyCursor(claim_row=(summary_id, "PENDING"))).claim_daily_summary(
        summary_date=date(2027, 3, 11), claimed_at=claimed_at
    )

    assert created.claimed is True
    assert created.delivery_status is DailySummaryDeliveryStatus.PENDING

    existing_id = uuid4()
    existing = _repository(DailyCursor(existing_row=(existing_id, "SENT"))).claim_daily_summary(
        summary_date=date(2027, 3, 11), claimed_at=claimed_at
    )

    assert existing.summary_id == existing_id
    assert existing.claimed is False
    assert existing.delivery_status is DailySummaryDeliveryStatus.SENT


def test_daily_summary_delivery_updates_only_pending_record() -> None:
    cursor = DailyCursor()
    repository = _repository(cursor)
    summary_id = uuid4()
    sent_at = datetime(2027, 3, 11, 11, 24, tzinfo=UTC)

    repository.mark_daily_summary_sent(
        summary_id=summary_id,
        telegram_message_id="123",
        sent_at=sent_at,
    )
    repository.mark_daily_summary_failed(summary_id=summary_id, error_code="TelegramError")

    updates = [
        params
        for query, params in cursor.executions
        if query.startswith("UPDATE daily_summary_history")
    ]
    assert updates[0] == (sent_at, "SENT", "123", sent_at, None, summary_id)
    assert updates[1][1:] == ("FAILED", None, None, "TelegramError", summary_id)


def test_daily_summary_delivery_rejects_non_pending_record() -> None:
    repository = _repository(DailyCursor(update_count=0))

    with pytest.raises(StorageError, match="Pending daily summary"):
        repository.mark_daily_summary_failed(summary_id=uuid4(), error_code="TelegramError")

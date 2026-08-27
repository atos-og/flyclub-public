"""PostgreSQL persistence isolated for the flexible-market radar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.flexible_market_models import (
    CalendarFare,
    FlexibleMarketDefinition,
    FlexibleMarketPeriod,
)
from flyclub.models import FlightOption, PriceObservation, SearchOutcome, SearchStatus
from flyclub.storage.postgres import StorageError, database_url_from_env, option_fingerprint


class FlexibleDecision(StrEnum):
    SEND = "SEND"
    SUPPRESS = "SUPPRESS"


class FlexibleDeliveryStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class FlexibleAlertRecord:
    alert_id: UUID
    created: bool
    delivery_status: FlexibleDeliveryStatus


@dataclass(frozen=True, slots=True)
class LastFlexibleAlert:
    price: Decimal
    observed_at: datetime
    departure_date: date
    arrival_airport: str


class _ConnectionFactory(Protocol):
    def __call__(self, database_url: str) -> Any: ...


def _option_legs(option: FlightOption) -> list[dict[str, object | None]]:
    return [
        {
            "journey_index": leg.journey_index,
            "origin_airport": leg.origin_airport,
            "destination_airport": leg.destination_airport,
            "departure_time": leg.departure_time.isoformat() if leg.departure_time else None,
            "arrival_time": leg.arrival_time.isoformat() if leg.arrival_time else None,
            "airline": leg.airline,
            "flight_number": leg.flight_number,
        }
        for leg in option.legs
    ]


def _arrival_airport(option: FlightOption) -> str:
    outbound = [leg for leg in option.legs if leg.journey_index == 0]
    if not outbound:
        raise ValueError("verified option does not contain an outbound journey")
    return outbound[-1].destination_airport


class FlexibleMarketRepository:
    def __init__(
        self,
        database_url: str,
        *,
        connect: _ConnectionFactory = psycopg.connect,
    ) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise StorageError("A PostgreSQL connection URL is required")
        self._database_url = database_url
        self._connect = connect

    @classmethod
    def from_env(cls) -> FlexibleMarketRepository:
        return cls(database_url_from_env())

    def record_check(
        self,
        *,
        run_id: UUID,
        market: FlexibleMarketDefinition,
        period: FlexibleMarketPeriod,
        outcome: SearchOutcome,
        calendar_fare: CalendarFare | None,
        provider_requests: int,
        checked_at: datetime,
    ) -> UUID:
        if checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")
        option = outcome.options[0] if outcome.status is SearchStatus.SUCCESS else None
        if (calendar_fare is None) != (option is None):
            raise ValueError("successful checks require both calendar and verified prices")
        check_id = uuid4()
        legs = _option_legs(option) if option is not None else None
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO flexible_market_checks (
                        id, run_id, market_key, market_label, period_key, period_label,
                        checked_at, status, provider_requests, window_start, window_end,
                        origin_airports, destination_airports, trip_duration_days, passengers,
                        cabin, max_stops, minimum_deal_score, departure_date, return_date,
                        arrival_airport, calendar_price, best_price, currency, result_count,
                        stops, duration_minutes, booking_url, google_flights_url,
                        itinerary_hash, legs, error_code, error_message
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (run_id, market_key, period_key) DO NOTHING
                    RETURNING id
                    """,
                    (
                        check_id,
                        run_id,
                        market.key,
                        market.label,
                        period.key,
                        period.label,
                        checked_at,
                        outcome.status.value,
                        provider_requests,
                        period.start_date,
                        period.end_date,
                        sorted(market.origin_airports),
                        sorted(market.destination_airports),
                        market.trip_duration_days,
                        market.passengers,
                        market.cabin.value,
                        market.max_stops.value,
                        period.minimum_deal_score,
                        calendar_fare.departure_date if calendar_fare else None,
                        calendar_fare.return_date if calendar_fare else None,
                        _arrival_airport(option) if option else None,
                        calendar_fare.price if calendar_fare else None,
                        option.price if option else None,
                        option.currency if option else market.currency,
                        len(outcome.options),
                        option.stops if option else None,
                        option.duration_minutes if option else None,
                        option.booking_url if option else None,
                        option.google_flights_url if option else None,
                        option_fingerprint(option) if option else None,
                        Jsonb(legs) if legs is not None else None,
                        outcome.error_code,
                        outcome.error_message,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute(
                        """
                        SELECT id FROM flexible_market_checks
                        WHERE run_id = %s AND market_key = %s AND period_key = %s
                        """,
                        (run_id, market.key, period.key),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise StorageError("Flexible-market check could not be resolved")
                    return existing[0]
                return inserted[0]
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Flexible-market check persistence ended unexpectedly")

    def price_history(
        self,
        *,
        market_key: str,
        period_key: str,
        exclude_check_id: UUID,
        limit: int = 500,
    ) -> tuple[PriceObservation, ...]:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT best_price, checked_at
                    FROM flexible_market_checks
                    WHERE market_key = %s AND period_key = %s
                      AND status = 'SUCCESS' AND best_price IS NOT NULL AND id <> %s
                    ORDER BY checked_at DESC
                    LIMIT %s
                    """,
                    (market_key, period_key, exclude_check_id, limit),
                )
                newest = cursor.fetchall()
                return tuple(
                    PriceObservation(price=row[0], observed_at=row[1]) for row in reversed(newest)
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Flexible-market history query ended unexpectedly")

    def update_evaluation(self, *, check_id: UUID, evaluation: RoutePriceEvaluation) -> None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE flexible_market_checks
                    SET sample_size = %s, confidence = %s, deal_score = %s,
                        classification = %s, provisional = %s
                    WHERE id = %s
                    """,
                    (
                        evaluation.statistics.sample_size,
                        evaluation.statistics.confidence.value,
                        evaluation.deal_score.score,
                        evaluation.deal_score.classification.value,
                        evaluation.deal_score.provisional,
                        check_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Flexible-market check was not found")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    def last_sent_alert(self, *, market_key: str, period_key: str) -> LastFlexibleAlert | None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT check_row.best_price, alert.sent_at, check_row.departure_date,
                           check_row.arrival_airport
                    FROM flexible_market_alert_history AS alert
                    JOIN flexible_market_checks AS check_row ON check_row.id = alert.check_id
                    WHERE alert.market_key = %s AND alert.period_key = %s
                      AND alert.decision = 'SEND' AND alert.delivery_status = 'SENT'
                    ORDER BY alert.sent_at DESC
                    LIMIT 1
                    """,
                    (market_key, period_key),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return LastFlexibleAlert(
                    price=row[0],
                    observed_at=row[1],
                    departure_date=row[2],
                    arrival_airport=row[3],
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Flexible-market last-alert query ended unexpectedly")

    def record_alert_decision(
        self,
        *,
        check_id: UUID,
        market_key: str,
        period_key: str,
        decision: FlexibleDecision,
        deal_score: int | None,
        reason_codes: tuple[str, ...],
        created_at: datetime,
    ) -> FlexibleAlertRecord:
        alert_id = uuid4()
        delivery = (
            FlexibleDeliveryStatus.PENDING
            if decision is FlexibleDecision.SEND
            else FlexibleDeliveryStatus.NOT_REQUESTED
        )
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO flexible_market_alert_history (
                        id, check_id, market_key, period_key, created_at, decision,
                        deal_score, reason_codes, delivery_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (check_id) DO NOTHING
                    RETURNING id, delivery_status
                    """,
                    (
                        alert_id,
                        check_id,
                        market_key,
                        period_key,
                        created_at,
                        decision.value,
                        deal_score,
                        list(reason_codes),
                        delivery.value,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is not None:
                    return FlexibleAlertRecord(
                        alert_id=inserted[0],
                        created=True,
                        delivery_status=FlexibleDeliveryStatus(inserted[1]),
                    )
                cursor.execute(
                    """
                    SELECT id, delivery_status FROM flexible_market_alert_history
                    WHERE check_id = %s
                    """,
                    (check_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise StorageError("Flexible-market alert decision could not be resolved")
                return FlexibleAlertRecord(
                    alert_id=existing[0],
                    created=False,
                    delivery_status=FlexibleDeliveryStatus(existing[1]),
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Flexible-market alert persistence ended unexpectedly")

    def mark_alert_sent(
        self, *, alert_id: UUID, telegram_message_id: str, sent_at: datetime | None = None
    ) -> None:
        self._mark_delivery(
            alert_id=alert_id,
            status=FlexibleDeliveryStatus.SENT,
            telegram_message_id=telegram_message_id,
            sent_at=sent_at or datetime.now(UTC),
            error_code=None,
        )

    def mark_alert_failed(self, *, alert_id: UUID, error_code: str) -> None:
        self._mark_delivery(
            alert_id=alert_id,
            status=FlexibleDeliveryStatus.FAILED,
            telegram_message_id=None,
            sent_at=None,
            error_code=error_code,
        )

    def _mark_delivery(
        self,
        *,
        alert_id: UUID,
        status: FlexibleDeliveryStatus,
        telegram_message_id: str | None,
        sent_at: datetime | None,
        error_code: str | None,
    ) -> None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE flexible_market_alert_history
                    SET delivery_status = %s, telegram_message_id = %s, sent_at = %s,
                        error_code = %s
                    WHERE id = %s AND delivery_status = 'PENDING'
                    """,
                    (status.value, telegram_message_id, sent_at, error_code, alert_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Flexible-market alert delivery was not pending")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    @staticmethod
    def _raise_sanitized(error: psycopg.Error) -> None:
        raise StorageError(f"Database operation failed ({type(error).__name__})") from None

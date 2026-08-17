"""PostgreSQL repository with idempotent writes and sanitized errors."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from flyclub.alerts.engine import AlertDecision
from flyclub.alerts.service import AlertDecisionRecord, AlertDeliveryStatus
from flyclub.analysis.evaluator import ShadowScoreEvaluation
from flyclub.daily_summary import (
    DailyPriceSnapshot,
    DailySummaryClaim,
    DailySummaryDeliveryStatus,
)
from flyclub.health import HealthNotificationKind, ProviderHealthState, ProviderHealthStatus
from flyclub.models import (
    FlightOption,
    PriceObservation,
    RouteDefinition,
    SearchOutcome,
    SearchStatus,
)

DATABASE_URL_ENV = "DATABASE_URL"


class StorageError(RuntimeError):
    """A database operation failed without exposing connection details."""


class StorageConfigError(StorageError):
    """Database configuration is missing or invalid."""


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"


def database_url_from_env() -> str:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise StorageConfigError("DATABASE_URL is not configured")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise StorageConfigError("DATABASE_URL must be a PostgreSQL connection URL")
    return database_url


def _now() -> datetime:
    return datetime.now(UTC)


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


def option_fingerprint(option: FlightOption) -> str:
    """Return a stable itinerary fingerprint without volatile provider URLs."""

    payload = {
        "price": str(option.price),
        "currency": option.currency,
        "stops": option.stops,
        "duration_minutes": option.duration_minutes,
        "legs": _option_legs(option),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PostgresRepository:
    """Persist monitor execution truth through short PostgreSQL transactions."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise StorageConfigError("A PostgreSQL connection URL is required")
        self._database_url = database_url
        self._connect = connect

    @classmethod
    def from_env(cls) -> PostgresRepository:
        return cls(database_url_from_env())

    def start_run(
        self,
        *,
        config_fingerprint: str,
        provider: str,
        planned_routes: int,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> UUID:
        selected_run_id = run_id or uuid4()
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO monitor_runs (
                        id, config_fingerprint, provider, started_at, status, planned_routes
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        selected_run_id,
                        config_fingerprint,
                        provider,
                        started_at or _now(),
                        RunStatus.RUNNING.value,
                        planned_routes,
                    ),
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        return selected_run_id

    def record_route_check(
        self,
        *,
        run_id: UUID,
        route: RouteDefinition,
        outcome: SearchOutcome,
        checked_at: datetime | None = None,
    ) -> UUID:
        """Atomically persist one route outcome and its normalized options.

        The `(run, route, provider)` uniqueness constraint makes a repeated call a no-op.
        """

        selected_checked_at = checked_at or _now()
        check_id = uuid4()
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                route_id = self._upsert_route(cursor, route, selected_checked_at)
                cursor.execute(
                    """
                    INSERT INTO route_checks (
                        id, run_id, route_id, provider, checked_at, status,
                        result_count, best_price, currency, error_code, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, route_id, provider) DO NOTHING
                    RETURNING id
                    """,
                    (
                        check_id,
                        run_id,
                        route_id,
                        outcome.provider,
                        selected_checked_at,
                        outcome.status.value,
                        len(outcome.options),
                        self._best_price(outcome),
                        route.currency,
                        outcome.error_code,
                        outcome.error_message,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute(
                        """
                        SELECT id FROM route_checks
                        WHERE run_id = %s AND route_id = %s AND provider = %s
                        """,
                        (run_id, route_id, outcome.provider),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise StorageError("Idempotent route check could not be resolved")
                    return existing[0]

                persisted_check_id = inserted[0]
                self._insert_options(
                    cursor,
                    check_id=persisted_check_id,
                    options=outcome.options,
                    captured_at=selected_checked_at,
                )
                return persisted_check_id
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Route check persistence ended unexpectedly")

    def finish_run(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
        successful_routes: int,
        empty_routes: int,
        failed_routes: int,
        finished_at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE monitor_runs
                    SET finished_at = %s, status = %s, successful_routes = %s,
                        empty_routes = %s, failed_routes = %s,
                        error_code = %s, error_message = %s
                    WHERE id = %s
                    """,
                    (
                        finished_at or _now(),
                        status.value,
                        successful_routes,
                        empty_routes,
                        failed_routes,
                        error_code,
                        error_message,
                        run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Monitor run was not found")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    def best_price_history(
        self,
        *,
        route_key: str,
        exclude_check_id: UUID,
        limit: int = 500,
    ) -> tuple[Decimal, ...]:
        """Load prior successful best prices, explicitly excluding the current check."""

        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rc.best_price
                    FROM route_checks AS rc
                    JOIN monitored_routes AS mr ON mr.id = rc.route_id
                    WHERE mr.route_key = %s
                      AND rc.status = 'SUCCESS'
                      AND rc.best_price IS NOT NULL
                      AND rc.id <> %s
                    ORDER BY rc.checked_at DESC
                    LIMIT %s
                    """,
                    (route_key, exclude_check_id, limit),
                )
                return tuple(row[0] for row in cursor.fetchall())
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Price history query ended unexpectedly")

    def price_history(
        self,
        *,
        route_key: str,
        exclude_check_id: UUID,
        limit: int = 500,
    ) -> tuple[PriceObservation, ...]:
        """Load prior successful observations in chronological order."""

        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rc.best_price, rc.checked_at
                    FROM route_checks AS rc
                    JOIN monitored_routes AS mr ON mr.id = rc.route_id
                    WHERE mr.route_key = %s
                      AND rc.status = 'SUCCESS'
                      AND rc.best_price IS NOT NULL
                      AND rc.id <> %s
                    ORDER BY rc.checked_at DESC
                    LIMIT %s
                    """,
                    (route_key, exclude_check_id, limit),
                )
                newest_first = cursor.fetchall()
                return tuple(
                    PriceObservation(price=row[0], observed_at=row[1])
                    for row in reversed(newest_first)
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Price observation query ended unexpectedly")

    def last_sent_alert_price(self, *, route_key: str) -> PriceObservation | None:
        """Load the price and send time of the last successfully delivered route alert."""

        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rc.best_price, ah.sent_at
                    FROM alert_history AS ah
                    JOIN route_checks AS rc ON rc.id = ah.route_check_id
                    JOIN monitored_routes AS mr ON mr.id = ah.route_id
                    WHERE mr.route_key = %s
                      AND ah.decision = 'SEND'
                      AND ah.delivery_status = 'SENT'
                      AND rc.best_price IS NOT NULL
                      AND ah.sent_at IS NOT NULL
                    ORDER BY ah.sent_at DESC
                    LIMIT 1
                    """,
                    (route_key,),
                )
                row = cursor.fetchone()
                return None if row is None else PriceObservation(price=row[0], observed_at=row[1])
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Last alert price query ended unexpectedly")

    def latest_daily_prices(
        self,
        *,
        route_keys: tuple[str, ...],
        observed_from: datetime,
        observed_until: datetime,
    ) -> tuple[DailyPriceSnapshot, ...]:
        """Return today's latest price and the last earlier reference for each route."""

        if not route_keys:
            return ()
        if observed_from.tzinfo is None or observed_until.tzinfo is None:
            raise ValueError("Daily price bounds must include a timezone")
        if observed_until < observed_from:
            raise ValueError("Daily price bounds are reversed")
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH requested_routes(route_key) AS (
                        SELECT unnest(%s::text[])
                    )
                    SELECT requested_routes.route_key,
                           current_price.best_price,
                           previous_price.best_price,
                           current_price.checked_at
                    FROM requested_routes
                    LEFT JOIN monitored_routes AS mr
                      ON mr.route_key = requested_routes.route_key
                    LEFT JOIN LATERAL (
                        SELECT rc.best_price, rc.checked_at
                        FROM route_checks AS rc
                        WHERE rc.route_id = mr.id
                          AND rc.status = 'SUCCESS'
                          AND rc.best_price IS NOT NULL
                          AND rc.checked_at >= %s
                          AND rc.checked_at <= %s
                        ORDER BY rc.checked_at DESC
                        LIMIT 1
                    ) AS current_price ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT rc.best_price
                        FROM route_checks AS rc
                        WHERE rc.route_id = mr.id
                          AND rc.status = 'SUCCESS'
                          AND rc.best_price IS NOT NULL
                          AND rc.checked_at < %s
                        ORDER BY rc.checked_at DESC
                        LIMIT 1
                    ) AS previous_price ON TRUE
                    ORDER BY array_position(%s::text[], requested_routes.route_key)
                    """,
                    (
                        list(route_keys),
                        observed_from,
                        observed_until,
                        observed_from,
                        list(route_keys),
                    ),
                )
                return tuple(
                    DailyPriceSnapshot(
                        route_key=row[0],
                        current_price=row[1],
                        previous_price=row[2],
                        observed_at=row[3],
                    )
                    for row in cursor.fetchall()
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Daily price query ended unexpectedly")

    def claim_daily_summary(
        self,
        *,
        summary_date: date,
        claimed_at: datetime,
    ) -> DailySummaryClaim:
        """Claim one date for delivery, allowing an explicit retry only after failure."""

        summary_id = uuid4()
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO daily_summary_history (
                        id, summary_date, created_at, updated_at, delivery_status
                    ) VALUES (%s, %s, %s, %s, 'PENDING')
                    ON CONFLICT (summary_date) DO UPDATE SET
                        updated_at = EXCLUDED.updated_at,
                        delivery_status = 'PENDING',
                        telegram_message_id = NULL,
                        sent_at = NULL,
                        error_code = NULL
                    WHERE daily_summary_history.delivery_status = 'FAILED'
                    RETURNING id, delivery_status
                    """,
                    (summary_id, summary_date, claimed_at, claimed_at),
                )
                claimed = cursor.fetchone()
                if claimed is not None:
                    return DailySummaryClaim(
                        summary_id=claimed[0],
                        claimed=True,
                        delivery_status=DailySummaryDeliveryStatus(claimed[1]),
                    )
                cursor.execute(
                    """
                    SELECT id, delivery_status
                    FROM daily_summary_history
                    WHERE summary_date = %s
                    """,
                    (summary_date,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise StorageError("Daily summary claim could not be persisted")
                return DailySummaryClaim(
                    summary_id=existing[0],
                    claimed=False,
                    delivery_status=DailySummaryDeliveryStatus(existing[1]),
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Daily summary claim ended unexpectedly")

    def mark_daily_summary_sent(
        self,
        *,
        summary_id: UUID,
        telegram_message_id: str,
        sent_at: datetime,
    ) -> None:
        self._update_daily_summary_delivery(
            summary_id=summary_id,
            status=DailySummaryDeliveryStatus.SENT,
            telegram_message_id=telegram_message_id,
            sent_at=sent_at,
            error_code=None,
        )

    def mark_daily_summary_failed(self, *, summary_id: UUID, error_code: str) -> None:
        self._update_daily_summary_delivery(
            summary_id=summary_id,
            status=DailySummaryDeliveryStatus.FAILED,
            telegram_message_id=None,
            sent_at=None,
            error_code=error_code,
        )

    def _update_daily_summary_delivery(
        self,
        *,
        summary_id: UUID,
        status: DailySummaryDeliveryStatus,
        telegram_message_id: str | None,
        sent_at: datetime | None,
        error_code: str | None,
    ) -> None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE daily_summary_history
                    SET updated_at = %s, delivery_status = %s, telegram_message_id = %s,
                        sent_at = %s, error_code = %s
                    WHERE id = %s AND delivery_status = 'PENDING'
                    """,
                    (
                        sent_at or _now(),
                        status.value,
                        telegram_message_id,
                        sent_at,
                        error_code,
                        summary_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Pending daily summary delivery was not found")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    def record_shadow_score(
        self,
        *,
        route_check_id: UUID,
        evaluated_at: datetime,
        evaluation: ShadowScoreEvaluation,
    ) -> None:
        """Persist one idempotent shadow score that never controls alert delivery."""

        metrics = {
            "p10": str(evaluation.statistics.p10)
            if evaluation.statistics.p10 is not None
            else None,
            "p50": str(evaluation.statistics.p50)
            if evaluation.statistics.p50 is not None
            else None,
            "p90": str(evaluation.statistics.p90)
            if evaluation.statistics.p90 is not None
            else None,
            "percentile_rank": (
                str(evaluation.statistics.percentile_rank)
                if evaluation.statistics.percentile_rank is not None
                else None
            ),
            "recorded_low": (
                str(evaluation.statistics.recorded_low)
                if evaluation.statistics.recorded_low is not None
                else None
            ),
            "trend_direction": evaluation.trend.direction.value,
            "trend_change_percent": (
                str(evaluation.trend.change_percent)
                if evaluation.trend.change_percent is not None
                else None
            ),
            "recent_drop_basis": (
                evaluation.recent_drop.basis.value if evaluation.recent_drop is not None else None
            ),
            "recent_drop_percent": (
                str(evaluation.recent_drop.drop_percent)
                if evaluation.recent_drop is not None
                else None
            ),
            "components": [
                {
                    "name": component.name.value,
                    "points": str(component.points),
                    "maximum_points": component.maximum_points,
                    "metric_percent": str(component.metric_percent),
                    "detail": component.detail,
                }
                for component in evaluation.deal_score.components
            ],
        }
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO deal_score_shadow (
                        route_check_id, route_id, version, evaluated_at, sample_size,
                        confidence, score, classification, provisional, metrics
                    )
                    SELECT rc.id, rc.route_id, %s, %s, %s, %s, %s, %s, %s, %s
                    FROM route_checks AS rc
                    WHERE rc.id = %s
                    ON CONFLICT (route_check_id, version) DO NOTHING
                    """,
                    (
                        evaluation.version,
                        evaluated_at,
                        evaluation.statistics.sample_size,
                        evaluation.statistics.confidence.value,
                        evaluation.deal_score.score,
                        evaluation.deal_score.classification.value,
                        evaluation.deal_score.provisional,
                        Jsonb(metrics),
                        route_check_id,
                    ),
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)

    def record_alert_decision(
        self,
        *,
        route_check_id: UUID,
        decision: AlertDecision,
        deal_score: int | None,
        reason_codes: tuple[str, ...],
        created_at: datetime,
    ) -> AlertDecisionRecord:
        """Persist one idempotent consolidated decision for a route check."""

        alert_id = uuid4()
        delivery_status = (
            AlertDeliveryStatus.PENDING
            if decision is AlertDecision.SEND
            else AlertDeliveryStatus.NOT_REQUESTED
        )
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_history (
                        id, route_id, route_check_id, created_at, decision, deal_score,
                        reason_codes, delivery_status
                    )
                    SELECT %s, rc.route_id, rc.id, %s, %s, %s, %s, %s
                    FROM route_checks AS rc
                    WHERE rc.id = %s
                    ON CONFLICT (route_check_id) DO NOTHING
                    RETURNING id, delivery_status
                    """,
                    (
                        alert_id,
                        created_at,
                        decision.value,
                        deal_score,
                        list(reason_codes),
                        delivery_status.value,
                        route_check_id,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is not None:
                    return AlertDecisionRecord(
                        alert_id=inserted[0],
                        created=True,
                        delivery_status=AlertDeliveryStatus(inserted[1]),
                    )
                cursor.execute(
                    """
                    SELECT id, delivery_status
                    FROM alert_history
                    WHERE route_check_id = %s
                    """,
                    (route_check_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise StorageError("Alert decision could not be persisted")
                return AlertDecisionRecord(
                    alert_id=existing[0],
                    created=False,
                    delivery_status=AlertDeliveryStatus(existing[1]),
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Alert decision persistence ended unexpectedly")

    def mark_alert_sent(
        self,
        *,
        alert_id: UUID,
        telegram_message_id: str,
        sent_at: datetime,
    ) -> None:
        self._update_alert_delivery(
            alert_id=alert_id,
            status=AlertDeliveryStatus.SENT,
            telegram_message_id=telegram_message_id,
            sent_at=sent_at,
            error_code=None,
        )

    def mark_alert_failed(self, *, alert_id: UUID, error_code: str) -> None:
        self._update_alert_delivery(
            alert_id=alert_id,
            status=AlertDeliveryStatus.FAILED,
            telegram_message_id=None,
            sent_at=None,
            error_code=error_code,
        )

    def _update_alert_delivery(
        self,
        *,
        alert_id: UUID,
        status: AlertDeliveryStatus,
        telegram_message_id: str | None,
        sent_at: datetime | None,
        error_code: str | None,
    ) -> None:
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE alert_history
                    SET delivery_status = %s, telegram_message_id = %s,
                        sent_at = %s, error_code = %s
                    WHERE id = %s AND delivery_status = 'PENDING'
                    """,
                    (
                        status.value,
                        telegram_message_id,
                        sent_at,
                        error_code,
                        alert_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Pending alert delivery was not found")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    def update_provider_health(
        self,
        *,
        provider: str,
        status: ProviderHealthStatus,
        attempted_at: datetime | None = None,
        error_code: str | None = None,
    ) -> ProviderHealthState:
        """Record one aggregate provider-health observation for a completed monitor run."""

        observed_at = attempted_at or _now()
        healthy = status is ProviderHealthStatus.HEALTHY
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO provider_health (
                        provider, current_status, last_attempt_at, last_success_at,
                        consecutive_problem_runs, incident_started_at, recovered_at,
                        last_error_code, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
                    ON CONFLICT (provider) DO UPDATE SET
                        current_status = EXCLUDED.current_status,
                        last_attempt_at = EXCLUDED.last_attempt_at,
                        last_success_at = CASE
                            WHEN EXCLUDED.current_status = 'HEALTHY'
                                THEN EXCLUDED.last_success_at
                            ELSE provider_health.last_success_at
                        END,
                        consecutive_problem_runs = CASE
                            WHEN EXCLUDED.current_status = 'HEALTHY' THEN 0
                            ELSE provider_health.consecutive_problem_runs + 1
                        END,
                        incident_started_at = CASE
                            WHEN EXCLUDED.current_status = 'HEALTHY' THEN NULL
                            WHEN provider_health.incident_started_at IS NULL
                                THEN EXCLUDED.incident_started_at
                            ELSE provider_health.incident_started_at
                        END,
                        recovered_at = CASE
                            WHEN EXCLUDED.current_status = 'HEALTHY'
                                 AND provider_health.current_status <> 'HEALTHY'
                                THEN EXCLUDED.updated_at
                            ELSE provider_health.recovered_at
                        END,
                        last_error_code = CASE
                            WHEN EXCLUDED.current_status = 'HEALTHY' THEN NULL
                            ELSE EXCLUDED.last_error_code
                        END,
                        problem_alert_sent_at = CASE
                            WHEN provider_health.current_status = 'HEALTHY'
                                 AND EXCLUDED.current_status <> 'HEALTHY'
                                THEN NULL
                            ELSE provider_health.problem_alert_sent_at
                        END,
                        recovery_alert_sent_at = CASE
                            WHEN provider_health.current_status = 'HEALTHY'
                                 AND EXCLUDED.current_status <> 'HEALTHY'
                                THEN NULL
                            ELSE provider_health.recovery_alert_sent_at
                        END,
                        updated_at = EXCLUDED.updated_at
                    RETURNING provider, current_status, last_success_at,
                              consecutive_problem_runs, incident_started_at,
                              problem_alert_sent_at, recovery_alert_sent_at
                    """,
                    (
                        provider,
                        status.value,
                        observed_at,
                        observed_at if healthy else None,
                        0 if healthy else 1,
                        None if healthy else observed_at,
                        None if healthy else error_code,
                        observed_at,
                    ),
                )
                persisted = cursor.fetchone()
                if persisted is None:
                    raise StorageError("Provider health state could not be persisted")
                return ProviderHealthState(
                    provider=persisted[0],
                    status=ProviderHealthStatus(persisted[1]),
                    last_success_at=persisted[2],
                    consecutive_problem_runs=persisted[3],
                    incident_started_at=persisted[4],
                    problem_alert_sent_at=persisted[5],
                    recovery_alert_sent_at=persisted[6],
                )
        except psycopg.Error as error:
            self._raise_sanitized(error)
        raise StorageError("Provider health persistence ended unexpectedly")

    def mark_provider_health_notification(
        self,
        *,
        provider: str,
        kind: HealthNotificationKind,
        sent_at: datetime | None = None,
    ) -> None:
        """Mark one delivered incident notification without allowing duplicate acknowledgement."""

        observed_at = sent_at or _now()
        if kind is HealthNotificationKind.PROBLEM:
            query = """
                UPDATE provider_health
                SET problem_alert_sent_at = %s
                WHERE provider = %s
                  AND current_status <> 'HEALTHY'
                  AND problem_alert_sent_at IS NULL
            """
        else:
            query = """
                UPDATE provider_health
                SET recovery_alert_sent_at = %s
                WHERE provider = %s
                  AND current_status = 'HEALTHY'
                  AND problem_alert_sent_at IS NOT NULL
                  AND recovery_alert_sent_at IS NULL
            """
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(query, (observed_at, provider))
                if cursor.rowcount != 1:
                    raise StorageError("Provider health notification was not pending")
        except psycopg.Error as error:
            self._raise_sanitized(error)

    @staticmethod
    def _best_price(outcome: SearchOutcome) -> Decimal | None:
        if outcome.status is not SearchStatus.SUCCESS:
            return None
        return min(option.price for option in outcome.options)

    @staticmethod
    def _upsert_route(cursor: Any, route: RouteDefinition, observed_at: datetime) -> UUID:
        route_id = uuid4()
        cursor.execute(
            """
            INSERT INTO monitored_routes (
                id, route_key, origin_group, origin_label, origin_role, origin_airports,
                positioning_notice, destination, destination_name, departure_date, return_date,
                passengers, cabin, currency, max_stops, alert_price, first_seen_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (route_key) DO UPDATE SET
                origin_label = EXCLUDED.origin_label,
                positioning_notice = EXCLUDED.positioning_notice,
                destination_name = EXCLUDED.destination_name,
                alert_price = EXCLUDED.alert_price,
                is_active = TRUE,
                last_seen_at = EXCLUDED.last_seen_at
            WHERE (
                monitored_routes.origin_group,
                monitored_routes.origin_role,
                monitored_routes.origin_airports,
                monitored_routes.destination,
                monitored_routes.departure_date,
                monitored_routes.return_date,
                monitored_routes.passengers,
                monitored_routes.cabin,
                monitored_routes.currency,
                monitored_routes.max_stops
            ) IS NOT DISTINCT FROM (
                EXCLUDED.origin_group,
                EXCLUDED.origin_role,
                EXCLUDED.origin_airports,
                EXCLUDED.destination,
                EXCLUDED.departure_date,
                EXCLUDED.return_date,
                EXCLUDED.passengers,
                EXCLUDED.cabin,
                EXCLUDED.currency,
                EXCLUDED.max_stops
            )
            RETURNING id
            """,
            (
                route_id,
                route.key,
                route.origin_group,
                route.origin_label,
                route.origin_role.value,
                sorted(route.origin_airports),
                route.positioning_notice,
                route.destination,
                route.destination_name,
                route.departure_date,
                route.return_date,
                route.passengers,
                route.cabin.value,
                route.currency,
                route.max_stops.value,
                route.alert_price,
                observed_at,
                observed_at,
            ),
        )
        persisted = cursor.fetchone()
        if persisted is None:
            raise StorageError("Monitored route could not be persisted")
        return persisted[0]

    @staticmethod
    def _insert_options(
        cursor: Any,
        *,
        check_id: UUID,
        options: tuple[FlightOption, ...],
        captured_at: datetime,
    ) -> None:
        parameters = [
            (
                uuid4(),
                check_id,
                rank,
                option.price,
                option.currency,
                option.stops,
                option.duration_minutes,
                option.booking_url,
                option.google_flights_url,
                option_fingerprint(option),
                Jsonb(_option_legs(option)),
                captured_at,
            )
            for rank, option in enumerate(options, start=1)
        ]
        if not parameters:
            return
        cursor.executemany(
            """
            INSERT INTO price_snapshots (
                id, route_check_id, option_rank, price, currency, stops, duration_minutes,
                booking_url, google_flights_url, itinerary_hash, legs, captured_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            parameters,
        )

    @staticmethod
    def _raise_sanitized(error: psycopg.Error) -> None:
        raise StorageError(f"Database operation failed ({type(error).__name__})") from None

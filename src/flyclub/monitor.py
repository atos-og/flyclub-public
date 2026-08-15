"""Sequential monitor orchestration independent of provider and database implementations."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from flyclub.alerts.engine import AlertDecision
from flyclub.alerts.health import HealthNotificationResult
from flyclub.alerts.service import AlertHandlingResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.health import ProviderHealthState, ProviderHealthStatus
from flyclub.models import (
    FlightOption,
    OriginPriceComparison,
    OriginRole,
    RouteDefinition,
    SearchOutcome,
    SearchStatus,
)
from flyclub.providers.base import FlightProvider
from flyclub.storage.postgres import RunStatus


class MonitorRepository(Protocol):
    def start_run(
        self,
        *,
        config_fingerprint: str,
        provider: str,
        planned_routes: int,
        run_id: UUID | None = None,
        started_at: datetime | None = None,
    ) -> UUID: ...

    def record_route_check(
        self,
        *,
        run_id: UUID,
        route: RouteDefinition,
        outcome: SearchOutcome,
        checked_at: datetime | None = None,
    ) -> UUID: ...

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
    ) -> None: ...

    def update_provider_health(
        self,
        *,
        provider: str,
        status: ProviderHealthStatus,
        attempted_at: datetime | None = None,
        error_code: str | None = None,
    ) -> ProviderHealthState: ...


class RouteAnalyzer(Protocol):
    def evaluate(
        self,
        *,
        route_key: str,
        current_check_id: UUID,
        current_price: Decimal,
        current_at: datetime,
    ) -> RoutePriceEvaluation: ...


class AlertHandler(Protocol):
    def handle(
        self,
        *,
        route: RouteDefinition,
        current_check_id: UUID,
        current_option: FlightOption,
        current_at: datetime,
        evaluation: RoutePriceEvaluation,
        origin_comparison: OriginPriceComparison | None = None,
    ) -> AlertHandlingResult: ...


class HealthHandler(Protocol):
    def handle(self, state: ProviderHealthState) -> HealthNotificationResult: ...


@dataclass(frozen=True, slots=True)
class _PendingAlert:
    route: RouteDefinition
    current_check_id: UUID
    current_option: FlightOption
    current_at: datetime
    evaluation: RoutePriceEvaluation


@dataclass(frozen=True, slots=True)
class _HomeReference:
    origin: str
    price: Decimal


@dataclass(frozen=True, slots=True)
class MonitorSummary:
    run_id: UUID
    status: RunStatus
    planned_routes: int
    successful_routes: int
    empty_routes: int
    failed_routes: int
    analyzed_routes: int
    alerts_sent: int
    alerts_suppressed: int
    health_alerts_sent: int
    persisted: bool


def _unexpected_failure(provider_name: str, error: Exception) -> SearchOutcome:
    return SearchOutcome(
        provider=provider_name,
        status=SearchStatus.TEMPORARY_FAILURE,
        error_code=type(error).__name__,
        error_message="Unexpected provider failure at the monitor boundary",
    )


def _run_status(*, successful: int, empty: int, failed: int) -> RunStatus:
    if failed == 0:
        return RunStatus.SUCCESS
    if successful + empty > 0:
        return RunStatus.PARTIAL
    return RunStatus.FAILURE


def _provider_health(
    outcomes: list[SearchOutcome],
) -> tuple[ProviderHealthStatus, str | None]:
    failures = [
        outcome
        for outcome in outcomes
        if outcome.status not in {SearchStatus.SUCCESS, SearchStatus.EMPTY}
    ]
    if not failures:
        return ProviderHealthStatus.HEALTHY, None
    provider_change = next(
        (outcome for outcome in failures if outcome.status is SearchStatus.PROVIDER_CHANGED),
        None,
    )
    if provider_change is not None:
        return ProviderHealthStatus.PROVIDER_CHANGED, provider_change.error_code
    if len(failures) == len(outcomes) and all(
        outcome.status is SearchStatus.TEMPORARY_FAILURE for outcome in failures
    ):
        return ProviderHealthStatus.UNAVAILABLE, failures[0].error_code
    return ProviderHealthStatus.DEGRADED, failures[0].error_code


def _comparison_key(route: RouteDefinition) -> tuple[object, ...]:
    return (
        route.destination,
        route.departure_date,
        route.return_date,
        route.passengers,
        route.cabin,
        route.currency,
        route.max_stops,
    )


def _actual_origin(route: RouteDefinition, option: FlightOption) -> str:
    return option.legs[0].origin_airport if option.legs else "/".join(route.origin_airports)


def run_monitor(
    *,
    routes: tuple[RouteDefinition, ...],
    config_fingerprint: str,
    provider: FlightProvider,
    max_results: int,
    repository: MonitorRepository | None,
    analyzer: RouteAnalyzer | None = None,
    alert_handler: AlertHandler | None = None,
    health_handler: HealthHandler | None = None,
    run_id: UUID | None = None,
) -> MonitorSummary:
    """Search every route sequentially and optionally persist every outcome."""

    if analyzer is not None and repository is None:
        raise ValueError("analyzer requires a persistence repository")
    if alert_handler is not None and analyzer is None:
        raise ValueError("alert handler requires an analyzer")
    if health_handler is not None and repository is None:
        raise ValueError("health handler requires a persistence repository")
    selected_run_id = run_id or uuid4()
    if repository is not None:
        repository.start_run(
            config_fingerprint=config_fingerprint,
            provider=provider.name,
            planned_routes=len(routes),
            run_id=selected_run_id,
        )

    successful = 0
    empty = 0
    failed = 0
    analyzed = 0
    alerts_sent = 0
    alerts_suppressed = 0
    health_alerts_sent = 0
    outcomes: list[SearchOutcome] = []
    pending_alerts: list[_PendingAlert] = []
    home_references: dict[tuple[object, ...], _HomeReference] = {}

    try:
        for route in routes:
            try:
                outcome = provider.search(route, max_results=max_results)
            except Exception as error:  # Last-resort boundary for a misbehaving adapter.
                outcome = _unexpected_failure(provider.name, error)

            if repository is not None:
                checked_at = datetime.now(UTC)
                check_id = repository.record_route_check(
                    run_id=selected_run_id,
                    route=route,
                    outcome=outcome,
                    checked_at=checked_at,
                )
                if analyzer is not None and outcome.status is SearchStatus.SUCCESS:
                    current_option = min(outcome.options, key=lambda option: option.price)
                    evaluation = analyzer.evaluate(
                        route_key=route.key,
                        current_check_id=check_id,
                        current_price=current_option.price,
                        current_at=checked_at,
                    )
                    analyzed += 1
                    if alert_handler is not None:
                        pending_alerts.append(
                            _PendingAlert(
                                route=route,
                                current_check_id=check_id,
                                current_option=current_option,
                                current_at=checked_at,
                                evaluation=evaluation,
                            )
                        )

                    if route.origin_role is OriginRole.HOME:
                        key = _comparison_key(route)
                        previous = home_references.get(key)
                        if previous is None or current_option.price < previous.price:
                            home_references[key] = _HomeReference(
                                origin=_actual_origin(route, current_option),
                                price=current_option.price,
                            )

            if outcome.status is SearchStatus.SUCCESS:
                successful += 1
            elif outcome.status is SearchStatus.EMPTY:
                empty += 1
            else:
                failed += 1
            outcomes.append(outcome)

        if alert_handler is not None:
            for pending in pending_alerts:
                home_reference = home_references.get(_comparison_key(pending.route))
                origin_comparison = (
                    OriginPriceComparison(
                        reference_origin=home_reference.origin,
                        reference_price=home_reference.price,
                    )
                    if pending.route.origin_role is OriginRole.POSITIONING
                    and home_reference is not None
                    else None
                )
                handling = alert_handler.handle(
                    route=pending.route,
                    current_check_id=pending.current_check_id,
                    current_option=pending.current_option,
                    current_at=pending.current_at,
                    evaluation=pending.evaluation,
                    origin_comparison=origin_comparison,
                )
                if handling.delivered:
                    alerts_sent += 1
                elif handling.alert.decision is AlertDecision.SUPPRESS:
                    alerts_suppressed += 1
    except Exception:
        if repository is not None:
            with suppress(Exception):  # Preserve the original error if recovery also fails.
                repository.finish_run(
                    run_id=selected_run_id,
                    status=RunStatus.FAILURE,
                    successful_routes=successful,
                    empty_routes=empty,
                    failed_routes=len(routes) - successful - empty,
                    error_code="MONITOR_ABORTED",
                    error_message="The monitor stopped before all routes were persisted",
                )
        raise

    status = _run_status(successful=successful, empty=empty, failed=failed)
    if repository is not None:
        repository.finish_run(
            run_id=selected_run_id,
            status=status,
            successful_routes=successful,
            empty_routes=empty,
            failed_routes=failed,
            error_code="ROUTE_FAILURES" if failed else None,
            error_message="One or more route searches failed" if failed else None,
        )
        health_status, health_error_code = _provider_health(outcomes)
        health_state = repository.update_provider_health(
            provider=provider.name,
            status=health_status,
            error_code=health_error_code,
        )
        if health_handler is not None and health_handler.handle(health_state).delivered:
            health_alerts_sent += 1

    return MonitorSummary(
        run_id=selected_run_id,
        status=status,
        planned_routes=len(routes),
        successful_routes=successful,
        empty_routes=empty,
        failed_routes=failed,
        analyzed_routes=analyzed,
        alerts_sent=alerts_sent,
        alerts_suppressed=alerts_suppressed,
        health_alerts_sent=health_alerts_sent,
        persisted=repository is not None,
    )

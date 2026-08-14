"""Sequential monitor orchestration independent of provider and database implementations."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from flyclub.models import RouteDefinition, SearchOutcome, SearchStatus
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


@dataclass(frozen=True, slots=True)
class MonitorSummary:
    run_id: UUID
    status: RunStatus
    planned_routes: int
    successful_routes: int
    empty_routes: int
    failed_routes: int
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


def run_monitor(
    *,
    routes: tuple[RouteDefinition, ...],
    config_fingerprint: str,
    provider: FlightProvider,
    max_results: int,
    repository: MonitorRepository | None,
    run_id: UUID | None = None,
) -> MonitorSummary:
    """Search every route sequentially and optionally persist every outcome."""

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

    try:
        for route in routes:
            try:
                outcome = provider.search(route, max_results=max_results)
            except Exception as error:  # Last-resort boundary for a misbehaving adapter.
                outcome = _unexpected_failure(provider.name, error)

            if repository is not None:
                repository.record_route_check(
                    run_id=selected_run_id,
                    route=route,
                    outcome=outcome,
                )

            if outcome.status is SearchStatus.SUCCESS:
                successful += 1
            elif outcome.status is SearchStatus.EMPTY:
                empty += 1
            else:
                failed += 1
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

    return MonitorSummary(
        run_id=selected_run_id,
        status=status,
        planned_routes=len(routes),
        successful_routes=successful,
        empty_routes=empty,
        failed_routes=failed,
        persisted=repository is not None,
    )

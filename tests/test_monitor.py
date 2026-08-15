from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from flyclub.alerts.engine import AlertDecision, AlertReason, AlertResult
from flyclub.alerts.health import HealthNotificationResult
from flyclub.alerts.service import AlertHandlingResult
from flyclub.config import load_config
from flyclub.health import HealthNotificationKind, ProviderHealthState, ProviderHealthStatus
from flyclub.models import (
    FlightOption,
    OriginPriceComparison,
    OriginRole,
    RouteDefinition,
    SearchOutcome,
    SearchStatus,
)
from flyclub.monitor import MonitorSummary, run_monitor
from flyclub.route_planner import config_fingerprint, plan_routes
from flyclub.storage.postgres import RunStatus

EXAMPLE_PATH = Path("config/routes.example.yaml")


class FakeProvider:
    name = "fake_flights"

    def __init__(self, outcomes: list[SearchOutcome | Exception]) -> None:
        self._outcomes = iter(outcomes)
        self.route_keys: list[str] = []

    def search(self, route: RouteDefinition, *, max_results: int) -> SearchOutcome:
        assert max_results == 5
        self.route_keys.append(route.key)
        result = next(self._outcomes)
        if isinstance(result, Exception):
            raise result
        return result


class FakeRepository:
    def __init__(self, *, fail_check: bool = False, fail_finish: bool = False) -> None:
        self.fail_check = fail_check
        self.fail_finish = fail_finish
        self.started: list[dict[str, object]] = []
        self.checks: list[dict[str, object]] = []
        self.finished: list[dict[str, object]] = []
        self.health: list[dict[str, object]] = []

    def start_run(self, **kwargs: object) -> UUID:
        self.started.append(kwargs)
        return kwargs["run_id"]  # type: ignore[return-value]

    def record_route_check(self, **kwargs: object) -> UUID:
        self.checks.append(kwargs)
        if self.fail_check:
            raise RuntimeError("database write failed")
        return uuid4()

    def finish_run(self, **kwargs: object) -> None:
        self.finished.append(kwargs)
        if self.fail_finish:
            raise RuntimeError("database finish failed")

    def update_provider_health(self, **kwargs: object) -> ProviderHealthState:
        self.health.append(kwargs)
        status = kwargs["status"]
        assert isinstance(status, ProviderHealthStatus)
        return ProviderHealthState(
            provider="fake_flights",
            status=status,
            last_success_at=None,
            consecutive_problem_runs=0 if status is ProviderHealthStatus.HEALTHY else 1,
            incident_started_at=None,
            problem_alert_sent_at=None,
            recovery_alert_sent_at=None,
        )


class FakeAnalyzer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.evaluations: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> object:
        self.evaluations.append(kwargs)
        if self.fail:
            raise RuntimeError("analysis failed")
        return object()


class FakeAlertHandler:
    def __init__(self, results: list[AlertHandlingResult]) -> None:
        self._results = iter(results)
        self.handled: list[dict[str, object]] = []

    def handle(self, **kwargs: object) -> AlertHandlingResult:
        self.handled.append(kwargs)
        return next(self._results)


class FakeHealthHandler:
    def __init__(self, result: HealthNotificationResult) -> None:
        self.result = result
        self.states: list[ProviderHealthState] = []

    def handle(self, state: ProviderHealthState) -> HealthNotificationResult:
        self.states.append(state)
        return self.result


def _routes(count: int = 3) -> tuple[RouteDefinition, ...]:
    return plan_routes(load_config(EXAMPLE_PATH))[:count]


def _success(price: str = "3000.00") -> SearchOutcome:
    return SearchOutcome(
        provider="fake_flights",
        status=SearchStatus.SUCCESS,
        options=(FlightOption(price=Decimal(price), currency="BRL", legs=()),),
    )


def _empty() -> SearchOutcome:
    return SearchOutcome(provider="fake_flights", status=SearchStatus.EMPTY)


def _failure() -> SearchOutcome:
    return SearchOutcome(
        provider="fake_flights",
        status=SearchStatus.TEMPORARY_FAILURE,
        error_code="TIMEOUT",
        error_message="Provider request failed",
    )


def _run(
    outcomes: list[SearchOutcome | Exception],
    *,
    repository: FakeRepository | None = None,
    analyzer: FakeAnalyzer | None = None,
    alert_handler: FakeAlertHandler | None = None,
    health_handler: FakeHealthHandler | None = None,
) -> tuple[MonitorSummary, FakeProvider]:
    routes = _routes(len(outcomes))
    provider = FakeProvider(outcomes)
    config = load_config(EXAMPLE_PATH)
    summary = run_monitor(
        routes=routes,
        config_fingerprint=config_fingerprint(config),
        provider=provider,
        max_results=5,
        repository=repository,
        analyzer=analyzer,
        alert_handler=alert_handler,
        health_handler=health_handler,
    )
    return summary, provider


def test_monitor_queries_routes_sequentially_and_persists_every_outcome() -> None:
    repository = FakeRepository()
    routes = _routes()

    summary, provider = _run([_success(), _empty(), _success("3100")], repository=repository)

    assert provider.route_keys == [route.key for route in routes]
    assert len(repository.started) == 1
    assert len(repository.checks) == 3
    assert len(repository.finished) == 1
    run_id = repository.started[0]["run_id"]
    assert all(check["run_id"] == run_id for check in repository.checks)
    assert repository.finished[0]["run_id"] == run_id
    assert repository.health[0]["status"] is ProviderHealthStatus.HEALTHY
    assert repository.health[0]["error_code"] is None
    assert summary.status is RunStatus.SUCCESS
    assert summary.successful_routes == 2
    assert summary.empty_routes == 1
    assert summary.failed_routes == 0
    assert summary.analyzed_routes == 0
    assert summary.alerts_sent == 0
    assert summary.alerts_suppressed == 0
    assert summary.health_alerts_sent == 0
    assert summary.persisted is True


def test_monitor_marks_mixed_provider_results_partial() -> None:
    repository = FakeRepository()

    summary, _ = _run([_success(), _failure(), _empty()], repository=repository)

    assert summary.status is RunStatus.PARTIAL
    assert summary.failed_routes == 1
    assert repository.finished[0]["status"] is RunStatus.PARTIAL
    assert repository.finished[0]["error_code"] == "ROUTE_FAILURES"
    assert repository.health[0]["status"] is ProviderHealthStatus.DEGRADED
    assert repository.health[0]["error_code"] == "TIMEOUT"


def test_monitor_marks_all_failed_results_as_failure() -> None:
    repository = FakeRepository()
    summary, _ = _run([_failure(), _failure()], repository=repository)

    assert summary.status is RunStatus.FAILURE
    assert summary.successful_routes == 0
    assert summary.empty_routes == 0
    assert summary.failed_routes == 2
    assert repository.health[0]["status"] is ProviderHealthStatus.UNAVAILABLE


def test_provider_format_change_has_health_priority() -> None:
    repository = FakeRepository()
    changed = SearchOutcome(
        provider="fake_flights",
        status=SearchStatus.PROVIDER_CHANGED,
        error_code="SEARCH_PARSE_ERROR",
    )

    _run([_failure(), changed, _success()], repository=repository)

    assert repository.health[0]["status"] is ProviderHealthStatus.PROVIDER_CHANGED
    assert repository.health[0]["error_code"] == "SEARCH_PARSE_ERROR"


def test_invalid_requests_do_not_mark_provider_unavailable() -> None:
    repository = FakeRepository()
    invalid = SearchOutcome(
        provider="fake_flights",
        status=SearchStatus.INVALID_REQUEST,
        error_code="INVALID_ROUTE",
    )

    _run([invalid, invalid], repository=repository)

    assert repository.health[0]["status"] is ProviderHealthStatus.DEGRADED
    assert repository.health[0]["error_code"] == "INVALID_ROUTE"


def test_monitor_converts_unexpected_provider_exception_and_continues() -> None:
    repository = FakeRepository()

    summary, provider = _run([RuntimeError("private detail"), _success()], repository=repository)

    assert len(provider.route_keys) == 2
    assert summary.status is RunStatus.PARTIAL
    first_outcome = repository.checks[0]["outcome"]
    assert isinstance(first_outcome, SearchOutcome)
    assert first_outcome.status is SearchStatus.TEMPORARY_FAILURE
    assert first_outcome.error_code == "RuntimeError"
    assert "private detail" not in (first_outcome.error_message or "")


def test_dry_run_searches_without_repository() -> None:
    summary, _ = _run([_success(), _empty()], repository=None)

    assert summary.status is RunStatus.SUCCESS
    assert summary.persisted is False


def test_monitor_analyzes_only_successful_persisted_checks() -> None:
    repository = FakeRepository()
    analyzer = FakeAnalyzer()

    summary, _ = _run([_success(), _empty(), _failure()], repository=repository, analyzer=analyzer)

    assert summary.analyzed_routes == 1
    assert len(analyzer.evaluations) == 1
    evaluation = analyzer.evaluations[0]
    assert evaluation["route_key"] == _routes()[0].key
    assert evaluation["current_price"] == Decimal("3000.00")
    assert evaluation["current_check_id"] is not None


def test_monitor_requires_persistence_for_analysis() -> None:
    try:
        _run([_success()], analyzer=FakeAnalyzer())
    except ValueError as error:
        assert str(error) == "analyzer requires a persistence repository"
    else:
        raise AssertionError("Analysis without persistence should fail")


def test_analysis_failure_aborts_and_closes_the_run() -> None:
    repository = FakeRepository()

    try:
        _run([_success()], repository=repository, analyzer=FakeAnalyzer(fail=True))
    except RuntimeError as error:
        assert str(error) == "analysis failed"
    else:
        raise AssertionError("Analysis failure should propagate")

    assert repository.finished[0]["status"] is RunStatus.FAILURE
    assert repository.finished[0]["error_code"] == "MONITOR_ABORTED"


def test_monitor_counts_delivered_and_suppressed_alerts() -> None:
    repository = FakeRepository()
    analyzer = FakeAnalyzer()
    sent = AlertHandlingResult(
        alert=AlertResult(AlertDecision.SEND, (AlertReason.PRICE_TARGET,)),
        delivered=True,
    )
    suppressed = AlertHandlingResult(
        alert=AlertResult(AlertDecision.SUPPRESS, (AlertReason.NO_TRIGGER,)),
        delivered=False,
    )
    handler = FakeAlertHandler([sent, suppressed])

    summary, _ = _run(
        [_success(), _success()],
        repository=repository,
        analyzer=analyzer,
        alert_handler=handler,
    )

    assert summary.alerts_sent == 1
    assert summary.alerts_suppressed == 1
    assert len(handler.handled) == 2


def test_positioning_alert_receives_best_home_price_regardless_of_route_order() -> None:
    config = load_config(EXAMPLE_PATH)
    all_routes = plan_routes(config)
    home = next(
        route
        for route in all_routes
        if route.destination == "LIS" and route.origin_role is OriginRole.HOME
    )
    positioning = next(
        route
        for route in all_routes
        if route.destination == "LIS" and route.origin_role is OriginRole.POSITIONING
    )
    repository = FakeRepository()
    analyzer = FakeAnalyzer()
    suppressed = AlertHandlingResult(
        alert=AlertResult(AlertDecision.SUPPRESS, (AlertReason.NO_TRIGGER,)),
        delivered=False,
    )
    handler = FakeAlertHandler([suppressed, suppressed])

    run_monitor(
        routes=(positioning, home),
        config_fingerprint=config_fingerprint(config),
        provider=FakeProvider([_success("2500"), _success("3200")]),
        max_results=5,
        repository=repository,
        analyzer=analyzer,
        alert_handler=handler,
    )

    comparison = handler.handled[0]["origin_comparison"]
    assert comparison == OriginPriceComparison("CNF", Decimal("3200"))
    assert handler.handled[1]["origin_comparison"] is None


def test_alert_handler_requires_analyzer() -> None:
    repository = FakeRepository()
    handler = FakeAlertHandler([])

    try:
        _run([_success()], repository=repository, alert_handler=handler)
    except ValueError as error:
        assert str(error) == "alert handler requires an analyzer"
    else:
        raise AssertionError("Alert handling without analysis should fail")


def test_monitor_counts_delivered_health_alert() -> None:
    repository = FakeRepository()
    handler = FakeHealthHandler(
        HealthNotificationResult(kind=HealthNotificationKind.PROBLEM, delivered=True)
    )

    summary, _ = _run([_failure()], repository=repository, health_handler=handler)

    assert summary.health_alerts_sent == 1
    assert handler.states[0].status is ProviderHealthStatus.UNAVAILABLE


def test_health_handler_requires_persistence() -> None:
    handler = FakeHealthHandler(HealthNotificationResult(kind=None, delivered=False))

    try:
        _run([_success()], health_handler=handler)
    except ValueError as error:
        assert str(error) == "health handler requires a persistence repository"
    else:
        raise AssertionError("Health handling without persistence should fail")


def test_auxiliary_monitor_can_leave_provider_health_unchanged() -> None:
    repository = FakeRepository()
    routes = _routes(1)

    summary = run_monitor(
        routes=routes,
        config_fingerprint="flexible",
        provider=FakeProvider([_success()]),
        max_results=5,
        repository=repository,
        update_health=False,
    )

    assert summary.status is RunStatus.SUCCESS
    assert repository.health == []


def test_monitor_attempts_to_finish_failed_run_after_persistence_error() -> None:
    repository = FakeRepository(fail_check=True)

    try:
        _run([_success(), _success()], repository=repository)
    except RuntimeError as error:
        assert str(error) == "database write failed"
    else:
        raise AssertionError("The persistence error should propagate")

    assert repository.finished[0]["status"] is RunStatus.FAILURE
    assert repository.finished[0]["failed_routes"] == 2
    assert repository.finished[0]["error_code"] == "MONITOR_ABORTED"


def test_monitor_preserves_original_error_when_failure_update_also_fails() -> None:
    repository = FakeRepository(fail_check=True, fail_finish=True)

    try:
        _run([_success()], repository=repository)
    except RuntimeError as error:
        assert str(error) == "database write failed"
    else:
        raise AssertionError("The original persistence error should propagate")

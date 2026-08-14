from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from flyclub.models import (
    CabinClass,
    FlightLeg,
    FlightOption,
    MaxStops,
    OriginRole,
    RouteDefinition,
    SearchOutcome,
    SearchStatus,
)
from flyclub.storage.postgres import (
    PostgresRepository,
    RunStatus,
    StorageConfigError,
    StorageError,
    database_url_from_env,
    option_fingerprint,
)


class FakeCursor:
    def __init__(
        self,
        *,
        duplicate_check_id: UUID | None = None,
        update_count: int = 1,
        history: tuple[Decimal, ...] = (),
    ) -> None:
        self.duplicate_check_id = duplicate_check_id
        self.rowcount = update_count
        self.history = history
        self.executions: list[tuple[str, Any]] = []
        self.batches: list[tuple[str, list[tuple[Any, ...]]]] = []
        self._result: tuple[Any, ...] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: Any = None, **_kwargs: Any) -> None:
        normalized = " ".join(query.split())
        self.executions.append((normalized, params))
        if normalized.startswith("INSERT INTO monitored_routes"):
            self._result = (uuid4(),)
        elif normalized.startswith("INSERT INTO route_checks"):
            self._result = None if self.duplicate_check_id else (params[0],)
        elif normalized.startswith("SELECT id FROM route_checks"):
            self._result = (self.duplicate_check_id,) if self.duplicate_check_id else None
        else:
            self._result = None

    def executemany(self, query: str, params: list[tuple[Any, ...]]) -> None:
        self.batches.append((" ".join(query.split()), params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._result

    def fetchall(self) -> list[tuple[Decimal]]:
        return [(price,) for price in self.history]


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def _repository(cursor: FakeCursor) -> PostgresRepository:
    def connect(database_url: str) -> FakeConnection:
        assert database_url == "postgresql://test.invalid/flyclub"
        return FakeConnection(cursor)

    return PostgresRepository("postgresql://test.invalid/flyclub", connect=connect)


def _route() -> RouteDefinition:
    return RouteDefinition(
        key="from_bh-lis-abc123",
        origin_group="from_bh",
        origin_label="Belo Horizonte",
        origin_role=OriginRole.HOME,
        origin_airports=("CNF",),
        positioning_notice=None,
        destination="LIS",
        destination_name="Lisboa",
        departure_date=date(2027, 3, 10),
        return_date=date(2027, 3, 20),
        passengers=1,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ONE_OR_FEWER_STOPS,
        alert_price=Decimal("3200.00"),
    )


def _option(price: str, *, url: str = "https://www.google.com/travel/flights/a") -> FlightOption:
    return FlightOption(
        price=Decimal(price),
        currency="BRL",
        stops=1,
        duration_minutes=720,
        google_flights_url=url,
        legs=(
            FlightLeg(
                journey_index=0,
                origin_airport="CNF",
                destination_airport="LIS",
                departure_time=datetime(2027, 3, 10, 12, tzinfo=UTC),
                arrival_time=datetime(2027, 3, 11, 5, tzinfo=UTC),
                airline="TP",
                flight_number="TP104",
            ),
        ),
    )


def _execution(cursor: FakeCursor, prefix: str) -> tuple[str, Any]:
    return next(item for item in cursor.executions if item[0].startswith(prefix))


def test_start_and_finish_run_persist_explicit_execution_state() -> None:
    cursor = FakeCursor()
    repository = _repository(cursor)
    run_id = uuid4()
    started_at = datetime(2027, 1, 1, tzinfo=UTC)

    assert (
        repository.start_run(
            config_fingerprint="a" * 64,
            provider="google_flights",
            planned_routes=6,
            run_id=run_id,
            started_at=started_at,
        )
        == run_id
    )
    repository.finish_run(
        run_id=run_id,
        status=RunStatus.PARTIAL,
        successful_routes=4,
        empty_routes=1,
        failed_routes=1,
        finished_at=started_at,
        error_code="ROUTE_FAILURES",
    )

    _, start_params = _execution(cursor, "INSERT INTO monitor_runs")
    _, finish_params = _execution(cursor, "UPDATE monitor_runs")
    assert start_params == (run_id, "a" * 64, "google_flights", started_at, "RUNNING", 6)
    assert finish_params[1:5] == ("PARTIAL", 4, 1, 1)


def test_successful_route_check_stores_best_decimal_and_ranked_options() -> None:
    cursor = FakeCursor()
    repository = _repository(cursor)
    expensive = _option("4100.10")
    cheapest = _option("3899.90", url="https://www.google.com/travel/flights/b")
    outcome = SearchOutcome(
        provider="google_flights",
        status=SearchStatus.SUCCESS,
        options=(expensive, cheapest),
    )

    check_id = repository.record_route_check(
        run_id=uuid4(),
        route=_route(),
        outcome=outcome,
        checked_at=datetime(2027, 1, 1, tzinfo=UTC),
    )

    _, check_params = _execution(cursor, "INSERT INTO route_checks")
    assert check_params[6] == 2
    assert check_params[7] == Decimal("3899.90")
    assert check_params[8] == "BRL"
    assert len(cursor.batches) == 1
    batch = cursor.batches[0][1]
    assert [row[2] for row in batch] == [1, 2]
    assert all(row[1] == check_id for row in batch)
    assert [row[3] for row in batch] == [Decimal("4100.10"), Decimal("3899.90")]


def test_duplicate_route_check_returns_existing_id_without_new_snapshots() -> None:
    existing_check_id = uuid4()
    cursor = FakeCursor(duplicate_check_id=existing_check_id)
    repository = _repository(cursor)
    outcome = SearchOutcome(
        provider="google_flights",
        status=SearchStatus.SUCCESS,
        options=(_option("3900.00"),),
    )

    result = repository.record_route_check(run_id=uuid4(), route=_route(), outcome=outcome)

    assert result == existing_check_id
    assert cursor.batches == []
    _execution(cursor, "SELECT id FROM route_checks")


def test_empty_route_check_has_no_invented_price_or_snapshot() -> None:
    cursor = FakeCursor()
    repository = _repository(cursor)

    repository.record_route_check(
        run_id=uuid4(),
        route=_route(),
        outcome=SearchOutcome(provider="google_flights", status=SearchStatus.EMPTY),
    )

    _, params = _execution(cursor, "INSERT INTO route_checks")
    assert params[6] == 0
    assert params[7] is None
    assert cursor.batches == []


def test_best_price_history_explicitly_excludes_current_check() -> None:
    cursor = FakeCursor(history=(Decimal("4000.00"), Decimal("4200.00")))
    repository = _repository(cursor)
    current_check_id = uuid4()

    history = repository.best_price_history(
        route_key=_route().key,
        exclude_check_id=current_check_id,
        limit=25,
    )

    assert history == (Decimal("4000.00"), Decimal("4200.00"))
    _, params = _execution(cursor, "SELECT rc.best_price")
    assert params == (_route().key, current_check_id, 25)


def test_best_price_history_requires_positive_limit() -> None:
    repository = _repository(FakeCursor())

    with pytest.raises(ValueError, match="at least 1"):
        repository.best_price_history(
            route_key=_route().key,
            exclude_check_id=uuid4(),
            limit=0,
        )


def test_option_fingerprint_ignores_volatile_provider_url() -> None:
    first = _option("3900.00", url="https://example.com/first")
    second = _option("3900.00", url="https://example.com/second")

    assert option_fingerprint(first) == option_fingerprint(second)


def test_database_url_validation_never_echoes_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "not-postgres-super-secret"
    monkeypatch.setenv("DATABASE_URL", secret)

    with pytest.raises(StorageConfigError) as captured:
        database_url_from_env()

    assert secret not in str(captured.value)


def test_psycopg_errors_are_sanitized() -> None:
    secret = "postgresql://user:super-secret@test.invalid/flyclub"

    def failed_connect(_database_url: str) -> FakeConnection:
        raise psycopg.OperationalError(f"could not connect using {secret}")

    repository = PostgresRepository(secret, connect=failed_connect)

    with pytest.raises(StorageError) as captured:
        repository.start_run(
            config_fingerprint="a" * 64,
            provider="google_flights",
            planned_routes=1,
        )

    assert "OperationalError" in str(captured.value)
    assert "super-secret" not in str(captured.value)


def test_finish_run_rejects_unknown_run() -> None:
    repository = _repository(FakeCursor(update_count=0))

    with pytest.raises(StorageError, match="not found"):
        repository.finish_run(
            run_id=uuid4(),
            status=RunStatus.FAILURE,
            successful_routes=0,
            empty_routes=0,
            failed_routes=1,
        )

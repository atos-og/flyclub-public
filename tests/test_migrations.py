from __future__ import annotations

from typing import Any

import pytest

from flyclub.storage import migrations
from flyclub.storage.postgres import StorageError


class MigrationCursor:
    def __init__(self, applied: list[tuple[int, str]] | None = None) -> None:
        self.applied = applied or []
        self.executions: list[tuple[str, Any]] = []

    def __enter__(self) -> MigrationCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: Any = None, **_kwargs: Any) -> None:
        self.executions.append((query, params))

    def fetchall(self) -> list[tuple[int, str]]:
        return self.applied


class MigrationConnection:
    def __init__(self, cursor: MigrationCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> MigrationConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> MigrationCursor:
        return self._cursor


def test_initial_migration_contains_all_principal_entities() -> None:
    discovered = migrations.discover_migrations()

    assert [migration.version for migration in discovered] == [1, 2]
    sql = discovered[0].sql
    for table in (
        "monitored_routes",
        "monitor_runs",
        "route_checks",
        "price_snapshots",
        "alert_history",
        "provider_health",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "NUMERIC(12, 2)" in sql
    assert "UNIQUE (run_id, route_id, provider)" in sql
    assert "problem_alert_sent_at" in discovered[1].sql
    assert "recovery_alert_sent_at" in discovered[1].sql


def test_apply_migrations_executes_pending_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MigrationCursor()
    monkeypatch.setattr(
        migrations.psycopg,
        "connect",
        lambda _database_url: MigrationConnection(cursor),
    )

    assert migrations.apply_migrations("postgresql://test.invalid/flyclub") == 2

    statements = [query for query, _ in cursor.executions]
    assert any("CREATE TABLE monitored_routes" in query for query in statements)
    assert any("ALTER TABLE provider_health" in query for query in statements)
    assert any("INSERT INTO flyclub_schema_migrations" in query for query in statements)


def test_apply_migrations_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    discovered = migrations.discover_migrations()
    cursor = MigrationCursor(
        applied=[(migration.version, migration.checksum) for migration in discovered]
    )
    monkeypatch.setattr(
        migrations.psycopg,
        "connect",
        lambda _database_url: MigrationConnection(cursor),
    )

    assert migrations.apply_migrations("postgresql://test.invalid/flyclub") == 0
    assert not any("CREATE TABLE monitored_routes" in query for query, _ in cursor.executions)


def test_applied_migration_checksum_cannot_change(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MigrationCursor(applied=[(1, "different")])
    monkeypatch.setattr(
        migrations.psycopg,
        "connect",
        lambda _database_url: MigrationConnection(cursor),
    )

    with pytest.raises(StorageError, match="checksum changed"):
        migrations.apply_migrations("postgresql://test.invalid/flyclub")


def test_migration_cli_loads_dotenv_without_overriding_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(migrations, "load_dotenv", lambda *, override: calls.append(override))
    monkeypatch.setattr(migrations, "apply_migrations", lambda: 0)

    assert migrations.cli([]) == 0
    assert calls == [False]
    assert "Applied migrations: 0" in capsys.readouterr().out

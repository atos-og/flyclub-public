"""Small, deterministic migration runner for Fly Club's PostgreSQL schema."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from importlib.resources import files

import psycopg

from flyclub.storage.postgres import StorageError, database_url_from_env

MIGRATIONS_PACKAGE = "flyclub.storage.sql"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def discover_migrations() -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    for resource in files(MIGRATIONS_PACKAGE).iterdir():
        if resource.name.endswith(".sql"):
            version_text, _, name = resource.name.partition("_")
            sql = resource.read_text(encoding="utf-8")
            migrations.append(
                Migration(
                    version=int(version_text),
                    name=name.removesuffix(".sql"),
                    checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                    sql=sql,
                )
            )
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise StorageError("Migration versions must be unique")
    return tuple(sorted(migrations, key=lambda migration: migration.version))


def apply_migrations(database_url: str | None = None) -> int:
    """Apply pending migrations and return how many were executed."""

    selected_url = database_url or database_url_from_env()
    try:
        with psycopg.connect(selected_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS flyclub_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('flyclub_schema_migrations'))")
            cursor.execute(
                "SELECT version, checksum FROM flyclub_schema_migrations ORDER BY version"
            )
            applied = dict(cursor.fetchall())

            applied_count = 0
            for migration in discover_migrations():
                existing_checksum = applied.get(migration.version)
                if existing_checksum is not None:
                    if existing_checksum != migration.checksum:
                        raise StorageError(
                            f"Applied migration {migration.version} checksum changed"
                        )
                    continue
                cursor.execute(migration.sql, prepare=False)
                cursor.execute(
                    """
                    INSERT INTO flyclub_schema_migrations (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
                applied_count += 1
            return applied_count
    except psycopg.Error as error:
        raise StorageError(f"Database migration failed ({type(error).__name__})") from None


def cli() -> int:
    parser = argparse.ArgumentParser(
        prog="flyclub-db-migrate", description="Apply Fly Club PostgreSQL migrations"
    )
    parser.parse_args()
    try:
        count = apply_migrations()
    except StorageError as error:
        print(f"Migration error: {error}")
        return 1
    print(f"Applied migrations: {count}")
    return 0

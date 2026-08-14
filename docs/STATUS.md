# Fly Club Status

## Current phase

Phase 4 code complete — sequential monitor runner with persisted and dry-run modes.

## Done

- Private Git repository cloned with `main` as the initial branch.
- Python 3.12 `src/` package skeleton and `flyclub` CLI created.
- Strict YAML configuration models with sanitized validation errors.
- Personal `config/routes.yaml`, `.env`, virtual environments, and secrets ignored by Git.
- Public `config/routes.example.yaml` with BH and São Paulo origin semantics.
- Route Planner expands two origin groups × three destinations into six comparable routes.
- Provider-neutral route, leg, option, outcome, status, and `FlightProvider` models created.
- Empty provider results are modeled separately from failures.
- Persistent guidance, architecture, decision, and operational status documents created.
- Foundation and persistent guidance committed and pushed to private `main`.
- `fli` 0.10.0 source pinned to a reviewed immutable Git commit.
- `GoogleFlightsProvider` builds round-trip searches with explicit airport groups.
- Provider results normalize to `Decimal` prices and provider-neutral legs/options.
- Empty, invalid, temporary failure, provider format change, and success outcomes are distinct.
- Bounded retry with exponential backoff is implemented at the provider boundary.
- Google Flights URLs are accepted only when they are valid HTTP(S) URLs.
- A controlled CLI option can search exactly one configured route.
- A real public-example CNF → LIS round-trip search returned five BRL options and deep links.
- PR #1 was validated, marked ready, and squash-merged into `main`.
- `psycopg` PostgreSQL support added without an ORM.
- Checksum-protected migration discovery and an advisory-locked migration CLI implemented.
- Initial schema created for routes, runs, checks, snapshots, alert history, and provider health.
- Monetary columns use `NUMERIC(12, 2)` and Python writes preserve `Decimal` values.
- Route-check writes are atomic and idempotent on `(run, route, provider)`.
- Successful checks store the best price separately from ranked normalized itinerary snapshots.
- Historical best-price queries require and exclude the current route-check ID.
- Repository database errors are sanitized so connection details are not echoed.
- PR #2 was validated and squash-merged into `main`.
- The monitor runner searches configured routes sequentially through `FlightProvider`.
- Every success, empty result, classified failure, and unexpected adapter failure is accounted for.
- Persisted runs receive deterministic `SUCCESS`, `PARTIAL`, or `FAILURE` status and counters.
- Aborted persisted cycles attempt a final failure update while preserving the original error.
- `--monitor --dry-run` exercises all provider calls without requiring or writing a database.
- Monitor summaries omit route endpoints, dates, prices, and booking URLs.

## In progress

- Phase 4 changes are on `agent/monitor-runner`, pending publication and review.

## Next

- Publish and integrate Phase 4.
- Provision a Supabase project, apply the initial migration, and run a live persistence smoke test.
- Add provider-health state updates after the live persistence path is verified.

## Known issues

- No Telegram delivery, GitHub Actions workflow, statistics, Deal Score, alert engine, alert
  deduplication, or provider-health updater exists yet.
- No live Supabase database has been provisioned or migrated; SQL behavior is currently covered by
  repository and migration-runner unit tests with fakes.
- The external dead-man switch remains proposed and requires user approval later.
- The user's system Python is not currently available on PATH; development validation used the
  local `.venv` created from the Codex Python 3.12 runtime.

## Last validation

Date: 2026-08-14

Tests:

- `pytest --cov=flyclub --cov-report=term-missing`: 47 passed, 90% total coverage.
- `ruff check .`: passed.
- `ruff format --check .`: passed after formatting.
- `python -m pip check`: passed.
- `git diff --check`: passed.

Manual checks:

- `flyclub --config config/routes.example.yaml --show-routes`: passed and planned six routes.
- `flyclub --config config/routes.example.yaml --search-route from_bh:LIS`: live provider search
  succeeded with five BRL round-trip options and valid Google Flights deep links.
- `.venv`, `.env`, and `config/routes.yaml`: confirmed ignored by Git.
- Repository scan found no committed credential values.
- `flyclub-db-migrate` without `DATABASE_URL`: failed safely without exposing a value.
- Migration discovery found the bundled `001_initial.sql`; no live PostgreSQL engine was available
  for an integration test.

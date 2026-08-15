# Fly Club Status

## Current phase

Phase 6 in progress — prior-only price statistics and confidence foundations.

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
- PR #3 was validated and squash-merged into `main`.
- A Supabase Free PostgreSQL project was connected through its Session Pooler.
- Migration `001_initial` was applied once and an immediate rerun applied zero migrations.
- Live synthetic persistence created one run, route check, and snapshot with correct relationships.
- The live history query excluded the current observation, and all synthetic rows were cleaned up.
- Local CLIs load ignored `.env` values without overriding external environment variables.
- Provider health derives `HEALTHY`, `DEGRADED`, `UNAVAILABLE`, and `PROVIDER_CHANGED` per run.
- Live health transitions preserved incident start and consecutive failures, recorded recovery, and
  cleaned up the synthetic health row.
- PR #5 was validated and merged into `main`.
- The ignored real route configuration was created and validated without entering Git history.
- A complete real dry run succeeded for every planned route, followed by a successful persisted
  collection cycle in Supabase.
- Pure `Decimal` statistics now calculate P10, P50, P90, percentile rank, recorded low, sample size,
  cold-start state, and configurable confidence.
- Percentile rank gives tied prices half weight, and the current price remains outside its own
  historical baseline.

## In progress

- Phase 6 statistics changes are on `feat/analysis-statistics`, pending publication and review.

## Next

- Publish and integrate the statistics foundation.
- Agree the deterministic Deal Score formula and connect statistics to persisted monitor results.

## Known issues

- Statistics are not connected to persisted monitor results yet.
- No Telegram delivery, GitHub Actions workflow, Deal Score, alert engine, or alert deduplication
  exists yet.
- The external dead-man switch remains proposed and requires user approval later.
- The user's system Python is not currently available on PATH; development validation used the
  local `.venv` created from the Codex Python 3.12 runtime.

## Last validation

Date: 2026-08-14

Tests:

- `pytest --cov=flyclub --cov-report=term-missing`: 66 passed, 92% total coverage.
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
- `flyclub --config config/routes.example.yaml --monitor` without `DATABASE_URL`: failed safely
  before any provider call.
- Live Supabase migration: one migration applied; immediate rerun applied zero.
- Live synthetic persistence: run/check/snapshot each verified once; current observation excluded;
  exact synthetic records removed afterward.
- Live synthetic provider health: consecutive problems, incident, recovery, and cleanup verified.
- `flyclub-db-migrate` loaded `DATABASE_URL` from ignored `.env` and applied zero pending migrations.
- Private configuration validation planned eight routes without printing their endpoints.
- Real provider dry run: eight successful routes, zero empty results, and zero failures.
- First real persisted cycle: eight successful routes, zero empty results, and zero failures.

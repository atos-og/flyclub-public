# Fly Club Status

## Current phase

Phase 2 complete — real `fli` provider and controlled single-route search.

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

## In progress

- Draft PR #1 is open for review and merge into `main`.

## Next

- Phase 3: design and implement the PostgreSQL schema and migrations.
- Add `psycopg` storage repositories and idempotent persistence tests.
- Store route checks separately from normalized price snapshots.

## Known issues

- No monitor runner, PostgreSQL schema, Telegram delivery, GitHub Actions workflow, statistics,
  Deal Score, alert engine, deduplication, or health monitor exists yet.
- The external dead-man switch remains proposed and requires user approval later.
- The user's system Python is not currently available on PATH; development validation used the
  local `.venv` created from the Codex Python 3.12 runtime.

## Last validation

Date: 2026-08-14

Tests:

- `pytest --cov=flyclub --cov-report=term-missing`: 23 passed, 88% total coverage.
- `ruff check .`: passed.
- `ruff format --check .`: passed after formatting.
- `git diff --check`: passed.

Manual checks:

- `flyclub --config config/routes.example.yaml --show-routes`: passed and planned six routes.
- `flyclub --config config/routes.example.yaml --search-route from_bh:LIS`: live provider search
  succeeded with five BRL round-trip options and valid Google Flights deep links.
- `.venv`, `.env`, and `config/routes.yaml`: confirmed ignored by Git.
- Repository scan found no committed credential values.

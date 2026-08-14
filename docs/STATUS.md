# Fly Club Status

## Current phase

Phase 1 — project foundation, safe configuration, provider-neutral models, and persistent project
guidance.

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

## In progress

- First coherent Git commit and push to the private GitHub repository.

## Next

- Finish versioning the foundation and documentation.
- Phase 2: add the `fli` dependency and implement a single-route manual provider spike.
- Normalize real round-trip results and verify a Google Flights deep link.
- Add provider tests without live network calls.

## Known issues

- No live flight provider is implemented.
- No monitor runner, PostgreSQL schema, Telegram delivery, GitHub Actions workflow, statistics,
  Deal Score, alert engine, deduplication, or health monitor exists yet.
- The external dead-man switch remains proposed and requires user approval later.
- The user's system Python is not currently available on PATH; development validation used the
  local `.venv` created from the Codex Python 3.12 runtime.

## Last validation

Date: 2026-08-14

Tests:

- `pytest --cov=flyclub --cov-report=term-missing`: 11 passed, 82% total coverage.
- `ruff check .`: passed.
- `ruff format --check .`: passed after formatting.
- `git diff --check`: passed.

Manual checks:

- `flyclub --config config/routes.example.yaml --show-routes`: passed and planned six routes.
- `.venv`, `.env`, and `config/routes.yaml`: confirmed ignored by Git.
- Repository scan found no committed credential values.

# Fly Club Status

## Current phase

V1 feature-complete; public-release candidate under security and clean-room validation.

## Implemented

- Python 3.12 package and CLI with strict YAML configuration and sanitized errors.
- Provider-neutral domain boundary with `fli` isolated in the Google Flights adapter.
- Sequential monitoring with explicit success, empty, temporary-failure, provider-change, and
  invalid-request outcomes.
- PostgreSQL persistence for runs, comparable routes, checks, normalized snapshots, alert
  decisions, provider health, daily summaries, and shadow scores.
- Exact `Decimal`/`NUMERIC` money handling and prior-only statistical baselines.
- P10/P50/P90, percentile rank, sample confidence, recent drop, historical trend, and deterministic
  explainable Deal Score.
- Consolidated, cooldown-protected Telegram opportunity alerts with compact validated offer links.
- Fixed-date monitoring, flexible-date scans, discovery markets, daily summaries, two-passenger
  confirmation, manual date matrices, and fare-risk comparisons.
- A `daily-median-v2` Deal Score running in shadow mode without controlling production alerts.
- Provider/run health, idempotent delivery, bounded retry, and an external heartbeat design.
- MIT license, security policy, contribution guide, acknowledgements, Dependabot configuration,
  and public/private deployment guidance.
- Optional private-workflow links supplied only at runtime, with no owner's operational URL
  hardcoded into the package.

## Public repository boundary

- Active public automation is limited to CI and dependency maintenance.
- Deployment workflows are inert `.example.yml` templates under `examples/github-actions`.
- Real schedules, manual trip inputs, logs, configuration, and credentials belong in a separate
  private deployment repository.
- Only synthetic route examples and empty environment-variable names are versioned.

## Validation

Date: 2026-08-24

- `pytest --cov=flyclub --cov-report=term-missing`: 218 passed with at least 90% coverage.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `python -m pip check`: passed.
- `git diff --check`: passed.
- All active workflow and inert deployment-template YAML parsed successfully.
- The package built successfully as a wheel with MIT metadata and its license file included.
- Tracked-file and reachable-history scans found no real credential patterns in the candidate
  source lineage.

## Remaining release gates

- Complete and document the 30-day `daily-median-v2` review no earlier than 2026-09-14.
- Create and validate the private deployment against the exact public candidate revision.
- Rotate every production credential and private endpoint after the repository split.
- Run independent secret/history scanning and a clean-room install.
- Enable public repository protection and security settings, then complete the manual go/no-go
  checklist in `docs/PUBLICATION.md`.

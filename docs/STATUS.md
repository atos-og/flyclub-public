# Fly Club Status

## Current phase

V1 feature-complete; sanitized public preview live, with the formal V1 release review pending.

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
- Rolling fixed-duration market discovery uses bounded calendar chunks, exact candidate
  verification, isolated PostgreSQL history, deterministic prior-only scoring, and a compact
  Telegram policy without changing the fixed-date monitor.

## Public repository boundary

- Active public automation is limited to CI and dependency maintenance.
- Deployment workflows, including rolling-market scanning, are inert `.example.yml` templates
  under `examples/github-actions`.
- Real schedules, manual trip inputs, logs, configuration, and credentials belong in a separate
  private deployment repository.
- Only synthetic route examples and empty environment-variable names are versioned.

## Validation

Date: 2026-09-02

- `pytest --cov=flyclub --cov-report=term --cov-fail-under=90`: 279 passed with 90% total coverage;
  CI now prevents coverage from falling below that threshold.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `python -m pip check`: passed.
- `git diff --check`: passed.
- All active workflow and inert deployment-template YAML parsed successfully.
- The package built successfully as a wheel with MIT metadata and its license file included.
- Tracked-file and reachable-history scans found no real credential patterns in the candidate
  source lineage.
- Gitleaks 8.30.1 scanned 40 reachable commits locally and again in GitHub Actions with zero
  unresolved findings; its release checksum is verified before every CI scan.
- A fresh authenticated clone installed every runtime/development dependency into a new virtual
  environment, validated the synthetic configuration, and repeated all 219 tests and quality
  checks successfully.
- The public preview recognizes the MIT license, permits only squash merges, deletes merged
  branches, gives workflows read-only default permissions, blocks workflow PR approvals, restricts
  Actions to SHA-pinned `actions/*`, and has dependency alerts and automated fixes enabled.
- Public visibility was enabled on 2026-08-28 after the latest CI and complete-history Gitleaks runs
  passed. The repository had no Actions Secrets, variables, artifacts, production workflows, or
  personal configuration.
- Secret scanning, push protection, vulnerability alerts, automated security fixes, and private
  vulnerability reporting are enabled. `main` requires strict `test` and `gitleaks` checks, pull
  requests, linear history, resolved conversations, and blocks force-pushes and deletion.
- Gitleaks runs on every branch push and pull request. CI also runs a repository-boundary checker
  that rejects tracked environment files, private/local configurations, credential-like files, or
  any enabled workflow outside the public CI/secret-scan allowlist. Pull requests expose the same
  safety checklist, and common private-key/credential filenames are ignored locally.
- The public README now presents the personal problem that motivated Fly Club in a concise
  third-person introduction, followed by a portfolio-oriented explanation of its intelligence,
  architecture, engineering decisions, security boundary, setup, limitations, and V1 path.
- The public README includes a fully synthetic alert preview and a Mermaid architecture diagram;
  neither visual contains production routes, dates, prices, identifiers, logs, or credentials.
- Flexible markets may constrain the complete trip to a fixed date window. The planner preserves
  return-date boundaries, isolates history with date-specific keys, and skips expired windows
  without provider calls; only synthetic examples and tests are public.

## Remaining release gates

- Keep the source visible as a public preview without creating a V1 tag or enabling any production
  workflow in this repository.
- Complete and document the 30-day `daily-median-v2` review no earlier than 2026-09-14.
- Create and validate the private deployment against the exact public candidate revision.
- Rotate every production credential and private endpoint after the repository split.
- Repeat the independent secret/history scan before the formal V1 release.

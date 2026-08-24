# Fly Club Project Guidance

## Mission

Fly Club is a personal radar for flight opportunities. Its primary question is:

> Has a genuinely exceptional fare appeared now that deserves the user's attention?

It is not a generic travel search engine, agency, dashboard, or purchase recommender.

## V1 principles

- Target R$ 0 infrastructure cost. Ask before adding any paid service or material cost risk.
- Use Python, with `fli` as the primary provider, behind Fly Club's `FlightProvider` boundary.
- Run short-lived monitoring jobs in GitHub Actions approximately every 90 minutes.
- Persist history in PostgreSQL on Supabase; do not use local SQLite as V1 persistence.
- Use Telegram as the only V1 notification channel.
- Do not add a frontend, web server, ML, or an LLM-based Deal Score in V1.
- Keep the Deal Score deterministic, testable, and explainable.
- Include P10, P50, P90, percentile rank, sample size, confidence, and simple trends.
- Use `Decimal` in Python and `NUMERIC` in PostgreSQL for money; never use `float`.
- Keep provider-specific types and imports out of domain, analysis, storage, and alert code.
- Distinguish successful, empty, temporary-failure, provider-change, and invalid-request results.
- Important failures must not happen silently; maintain provider health and run health.
- Never commit secrets, personal routes, real dates, destinations, or private healthcheck URLs.
- Keep the public source repository safe to clone and inspect at any reachable revision.
- Keep public source separate from the owner's private deployment; public
  Actions must never receive personal routes, dates, fare rules, or production credentials.
- Test critical rules, especially statistics, score, deduplication, money, URLs, and health.
- Prefer small, readable components and pure functions over speculative abstractions.
- Do not add dependencies or infrastructure without a concrete need.
- Never mix incompatible historical series after dates, currency, cabin, passengers, stops, or
  origin membership change.
- Evaluate the current observation against prior history; it must not influence its own baseline.
- Deal Score measures current price quality and exceptionalness, not merely travel urgency.
- Initially query providers sequentially to reduce rate-limit and thread-safety risks.

## Persistent context workflow

Before a relevant implementation:

1. Read this file.
2. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and `docs/STATUS.md`.
3. Inspect relevant code and tests.
4. Form a short internal plan, then implement.

After a relevant implementation:

1. Run relevant tests and validations and fix regressions.
2. Update `docs/STATUS.md` with verified facts.
3. Update architecture only when the real architecture changed.
4. Record only material new decisions.
5. Update this file only for permanent rules or useful commands.

Keep these files concise. Do not create per-feature `spec.md`, `plan.md`, or `tasks.md` files.

## Decision authority

Use engineering judgment for localized implementation details, helpers, mocks, tests, typing,
small refactors, logging details, and the choice between dataclasses and Pydantic.

Stop and consult the user with Problem / Options / Trade-offs / Recommendation before changing
the primary provider, abandoning `fli` or Supabase, adding Playwright, paid services, ML, a
frontend, the main schedule, alert policy, Deal Score semantics, product scope, or making a major
architectural refactor.

## Current development commands

Install Python 3.12 dependencies:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run lint and formatting checks:

```bash
ruff check .
ruff format --check .
```

Validate an ignored local configuration:

```bash
flyclub
```

Validate the public example and optionally inspect its planned routes:

```bash
flyclub --config config/routes.example.yaml --show-routes
```

Run one explicit live provider search for a configured route:

```bash
flyclub --config config/routes.example.yaml --search-route from_bh:LIS
```

This command performs real network requests through the unofficial provider and may reveal trip
details in local output.

Run every configured route sequentially without persistence or route details in the summary:

```bash
flyclub --monitor --dry-run
```

Run the persisted monitor after migrations and secure `DATABASE_URL` configuration:

```bash
flyclub --monitor
```

Apply pending PostgreSQL migrations after `DATABASE_URL` is supplied securely:

```bash
flyclub-db-migrate
```

Never pass the database URL as a command argument or print it. Migration tests use fakes; a live
database validation requires an external PostgreSQL/Supabase instance.

Local CLIs load the ignored `.env` with `override=False`. Environment variables supplied by CI or
the operating system always take precedence. Tests must mock local environment loading when they
assert missing-secret behavior and must never connect to the real `.env` database.

## Git

Make incremental, coherent commits. Avoid both giant mixed commits and trivial commit noise. Use
clear conventional-style subjects such as `chore:`, `docs:`, `feat(config):`, or
`test(provider):` when appropriate.

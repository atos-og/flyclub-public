# Fly Club

Fly Club is a personal radar for exceptional flight opportunities. It is designed to collect
flight prices periodically, build a trustworthy history, classify genuinely unusual prices, and
send low-noise Telegram alerts.

The project currently validates route configuration, searches Google Flights, persists every
result in PostgreSQL, and evaluates successful prices against prior-only history with deterministic
statistics, trend, confidence, and Deal Score. The monitor runs all configured routes sequentially
with safe aggregate output; alert delivery and scheduled execution are not configured yet.

## Principles

- Provider-specific code stays behind a small interface.
- Every monitoring cycle is persisted, including valid prices that do not generate alerts.
- Statistical claims are gated by sample size and confidence.
- Deal scores are deterministic and explainable.
- Secrets and personal trip configuration are never committed.

## Requirements

- Python 3.12+
- Git

## Local setup

Create and activate a virtual environment, then install the development dependencies:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create your private configuration from the public example:

```bash
cp config/routes.example.yaml config/routes.yaml
```

On Windows PowerShell, use:

```powershell
Copy-Item config/routes.example.yaml config/routes.yaml
```

`config/routes.yaml` is ignored by Git. Validate it with:

```bash
flyclub
```

Local commands automatically load the ignored `.env` file without overriding variables already
provided by the operating system or GitHub Actions. Keep real values only in `.env`; the tracked
`.env.example` must contain variable names with empty values.

To inspect the planned endpoints locally:

```bash
flyclub --show-routes
```

Avoid `--show-routes` in shared CI logs because destinations and dates can be personal.

To perform one explicit live search through `fli`:

```bash
flyclub --config config/routes.example.yaml --search-route from_bh:LIS
```

This uses the unofficial Google Flights interface, prints trip details locally, and does not store
or alert anything yet.

To exercise every configured route without storing results, use:

```bash
flyclub --monitor --dry-run
```

The summary prints counters only, not route endpoints, dates, prices, or booking URLs. This still
performs real network requests. After migrations have been applied and `DATABASE_URL` is available,
omit `--dry-run` to persist the complete monitor cycle:

```bash
flyclub --monitor
```

## PostgreSQL migrations

Fly Club reads its PostgreSQL connection string only from `DATABASE_URL`. After configuring an
empty Supabase/PostgreSQL database outside Git, apply all pending migrations with:

```bash
flyclub-db-migrate
```

Migrations are checksum-protected and serialized with a PostgreSQL advisory lock. The initial
schema keeps route checks separate from itinerary snapshots and uses `NUMERIC(12, 2)` for money.
Do not place the connection string in shell history, committed files, or command arguments.

At the end of each persisted monitor run, Fly Club records aggregate provider health as `HEALTHY`,
`DEGRADED`, `UNAVAILABLE`, or `PROVIDER_CHANGED`, including incident and recovery state.

## Configuration precedence

Fly Club loads configuration in this order:

1. YAML content in `FLYCLUB_ROUTES_YAML` (intended for GitHub Secrets).
2. A path passed with `--config`.
3. The path in `FLYCLUB_CONFIG_PATH`.
4. The ignored local file `config/routes.yaml`.

Only `config/routes.example.yaml` is versioned.

## Tests

```bash
pytest
ruff check .
```

## Security

Never commit `.env`, `config/routes.yaml`, database connection strings, Telegram credentials, or
private healthcheck URLs. `.env.example` contains variable names only. Validation errors are
formatted without echoing configuration values.

The repository will receive a dedicated security and documentation review before it is made
public.

## Planned V1

The V1 uses Python, the `fli` Google Flights provider, PostgreSQL on Supabase, GitHub Actions,
Telegram, and pytest. It will not include a web interface, machine learning, or browser automation.

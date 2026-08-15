# Fly Club

Fly Club is a personal radar for exceptional flight opportunities. It is designed to collect
flight prices periodically, build a trustworthy history, classify genuinely unusual prices, and
send low-noise Telegram alerts.

The project currently validates route configuration, searches Google Flights, persists every
result in PostgreSQL, evaluates successful prices against prior-only history with deterministic
statistics, trend, confidence, and Deal Score, and sends consolidated low-noise Telegram alerts.
The monitor runs all configured routes sequentially with safe aggregate output in a scheduled
GitHub Actions workflow.

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

A persisted cycle also records one idempotent alert decision per successful route check. A new
`SEND` decision is delivered through Telegram and marked `SENT` or `FAILED`; an existing decision
is never sent again. Telegram credentials are read only from `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`.

For positioning origins such as São Paulo, the monitor compares the fare with the best compatible
HOME-origin option found in the same run. When the savings meet
`alerts.positioning_context_min_savings` after subtracting the configured
`positioning_cost_estimate`, the message states gross savings, estimated round-trip positioning
cost for the configured passenger count, and estimated net savings. A positioning opportunity that
does not clear that net threshold is persisted as suppressed instead of being sent.

## GitHub Actions

The private monitor workflow supports manual dispatch and an external primary trigger every 90
minutes. Native GitHub schedules remain as duplicate-safe fallbacks 30 minutes later because
scheduled events are approximate and can be delayed. The workflow allows read access only to
repository contents and Actions run metadata, prevents overlapping monitor runs, applies pending
migrations, and runs the persisted monitor without printing private route details. Follow
[`docs/scheduling-externo.md`](docs/scheduling-externo.md) to configure the optional external
scheduler without exposing its repository-scoped token.

Configure these repository secrets before enabling or manually dispatching the monitor:

- `DATABASE_URL`
- `FLYCLUB_ROUTES_YAML` (the complete contents of the private routes YAML)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `HEALTHCHECKS_PING_URL` (the private base Ping URL for the single external heartbeat check)

On Windows PowerShell 5.1, upload the private YAML as raw UTF-8 bytes with input redirection:

```powershell
cmd.exe /d /c "gh secret set FLYCLUB_ROUTES_YAML --repo OWNER/flyclub < config\routes.yaml"
```

Replace `OWNER` with the repository owner. Do not use `Get-Content ... | gh secret set` in Windows
PowerShell 5.1: its native-command pipeline can transcode the YAML to UTF-16, which is rejected by
the Linux workflow. The command above does not print or commit the private configuration.

The workflow sends a best-effort `/start` ping before its main steps. Its final step runs even after
an earlier failure and sends either a success ping or `/fail` according to the job result. Pings use
a short timeout and bounded retries; a Healthchecks.io request failure never changes the monitor's
result. A missing `HEALTHCHECKS_PING_URL`, however, is treated like any other missing required
deployment secret.

Healthchecks.io monitors only whether the scheduled process starts and finishes. Provider health,
empty results, Deal Score, fare decisions, route monitoring, persistence, and Fly Club Telegram
notifications stay inside the application. Configure one Simple-schedule check named
`Fly Club Monitor`, with a 90-minute period and one-hour grace time, and use Healthchecks.io's
native Telegram integration for external workflow alerts.

The separate CI workflow runs tests, lint, and formatting checks for pull requests and pushes to
`main`. Reusable actions are pinned to immutable full commit SHAs.

When an automatic alert scores at least 80 with moderate or high confidence, it links to the
separate **Confirm fare for 2 passengers** workflow. Use Actions → that workflow → Run workflow,
enter one origin IATA code, destination, departure date, and return date. The spot check always
uses two Economy passengers in BRL, sends a clearly tagged Telegram message, and never reads or
writes the statistical database.

The independent **Scan flexible dates** workflow uses two daily shards at 04:33 and 16:33 Brasília
time. The first scans −3, −2, and −1 days; the second scans +1, +2, and +3 days. This preserves
trip duration, keeps provider calls sequential, and gives every offset one observation per day
without placing all 48 private searches in one job. Each date pair is an isolated statistical
series, and any Telegram opportunity starts with `🗓️ DATA FLEXÍVEL`. The fixed-date 90-minute
monitor remains unchanged.

The optional **Scan discovery markets** workflow is intentionally manual-only until its Actions
budget is approved. It plans 30 independent routes across the configured BH and São Paulo markets,
uses a score threshold of 60 for selected Americas/Brazil destinations and 90 for Europe, and
prefixes Telegram messages with `🔎 DESCOBERTA`. Discovery history never mixes with the main trip,
even when an airport is present in both lists.

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
After the configured number of consecutive problem runs (three by default), it sends one Telegram
warning. A reported incident receives one recovery message when the provider becomes healthy again;
both notifications remain pending for retry until a successful delivery is recorded.

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
private Healthchecks Ping URLs. `HEALTHCHECKS_PING_URL` belongs only in the ignored local `.env`
when needed for secure setup and in the GitHub Repository Secret of the same name. `.env.example`
contains variable names only. Validation errors are formatted without echoing configuration
values.

The repository will receive a dedicated security and documentation review before it is made
public.

## V1 scope

The V1 uses Python, the `fli` Google Flights provider, PostgreSQL on Supabase, GitHub Actions,
Telegram, and pytest. It will not include a web interface, machine learning, or browser automation.

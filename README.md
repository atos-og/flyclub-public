# Fly Club

[![CI](https://github.com/atos-og/flyclub-public/actions/workflows/ci.yml/badge.svg)](https://github.com/atos-og/flyclub-public/actions/workflows/ci.yml)
[![Secret scan](https://github.com/atos-og/flyclub-public/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/atos-og/flyclub-public/actions/workflows/secret-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fly Club is a personal radar for exceptional flight opportunities. It is designed to collect
flight prices periodically, build a trustworthy history, classify genuinely unusual prices, and
send low-noise Telegram alerts.

Fly Club is MIT-licensed open-source software. This repository contains only source code,
synthetic examples, public CI, and inert deployment templates. Personal production operation
belongs in a separate private repository; see
[the publication and deployment model](docs/PUBLICATION.md).

> **Project status:** public preview under active development. The source and security boundary are
> public now; the V1 release remains gated on the documented statistical and production review.

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
`TELEGRAM_CHAT_ID`. The optional `FLYCLUB_CONFIRMATION_WORKFLOW_URL` enables the two-passenger
confirmation reminder without hardcoding an owner's repository into the package.

For positioning origins such as São Paulo, the monitor compares the fare with the best compatible
HOME-origin option found in the same run. When the savings meet
`alerts.positioning_context_min_savings` after subtracting the configured
`positioning_cost_estimate`, the message states gross savings, estimated round-trip positioning
cost for the configured passenger count, and estimated net savings. A positioning opportunity that
does not clear that net threshold is persisted as suppressed instead of being sent.

## GitHub Actions

Only CI and dependency maintenance are active in this source repository. Deployment templates live
under [`examples/github-actions`](examples/github-actions) with the `.example.yml` suffix, so
GitHub cannot execute them here. Copy only the workflows you need into a separate private
deployment repository and review their permissions before enabling them.

The reference monitor workflow supports manual dispatch and an external primary trigger every 90
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

The reference **Send daily price summary** workflow runs every day at 08:23 Brasília time. It reads
the most recent successful price already persisted for each fixed-date route since local midnight,
compares it with the last earlier observation, and sends one compact Telegram message. It performs
no provider request, cannot create or suppress an opportunity alert, and uses a unique local date
in PostgreSQL to prevent duplicate daily delivery. A failed Telegram delivery may be retried; an
already pending or sent summary is not sent again.

The separate CI workflow runs tests, lint, and formatting checks for pull requests and pushes to
`main`. Reusable actions are pinned to immutable full commit SHAs.

When an automatic alert scores at least 80 with moderate or high confidence, it links to the
reference **Confirm fare for 2 passengers** workflow. In a private deployment, use Actions → that
workflow → Run workflow,
enter one origin IATA code, destination, departure date, and return date. The spot check always
uses two Economy passengers in BRL, sends a clearly tagged Telegram message, and never reads or
writes the statistical database.

The reference **Compare nearby travel dates** workflow varies departure and return independently
inside a selected ±1, ±2, or ±3-day window. A ±3-day comparison can perform up to 49 sequential
provider searches for one explicit origin/destination pair. It ranks the three cheapest successful
combinations, breaking equal-price ties by fewer stops, shorter duration, and smaller date change.
The Telegram result states the exact savings or extra cost versus the requested dates and explains
each date shift. It is a point-in-time comparison: it does not persist results, calculate Deal
Score, or change automatic alerts.

The reference **Compare fare flexibility** workflow compares two quoted fares after their exact rules
have been checked. For each fare, enter its total price, cancellation rule and fixed penalty,
change rule and fixed penalty, whether a future fare difference applies, the exact HTTP(S) source,
and the verification date. The deterministic ranking uses the greatest fixed financial exposure
from cancellation or change; price only breaks an equal-risk result. Sources older than seven days
block an automatic recommendation. Because `fli` does not expose fare rules, this workflow never
invents or scrapes them: the entered source and conditions remain authoritative and must still be
confirmed at checkout. It does not change the quoted price, history, Deal Score, or alerts.

The reference **Scan flexible dates** workflow uses two daily shards at 04:33 and 16:33 Brasília
time. The first scans −3, −2, and −1 days; the second scans +1, +2, and +3 days. This preserves
trip duration, keeps provider calls sequential, and gives every offset one observation per day
without placing all 48 private searches in one job. Each date pair is an isolated statistical
series, and any Telegram opportunity starts with `🗓️ DATA FLEXÍVEL`. The fixed-date 90-minute
monitor remains unchanged.

The reference **Scan discovery markets** workflow runs every Monday, Wednesday, and Saturday at 06:23
Brasília time and also supports manual dispatch. It plans 30 independent routes across the
configured BH and São Paulo markets, uses a score threshold of 60 for selected Americas/Brazil
destinations and 90 for Europe, and prefixes Telegram messages with `🔎 DESCOBERTA`. Discovery
history never mixes with the main trip, even when an airport is present in both lists.

The independent **Scan flexible travel markets** workflow looks for a fixed-duration trip anywhere
inside a rolling date window. It first reads the provider's calendar in bounded sequential chunks,
then verifies only the strongest calendar candidates with an exact round-trip search before storing
or alerting. Each calendar period has its own prior-only history and minimum Deal Score, so an
excellent near-term opportunity cannot be hidden by a cheaper fare from a later year. This job runs
twice daily by default, has its own concurrency group, tables, alert cooldown, configuration Secret,
and Telegram heading, and does not change the fixed-date monitor or its alerts.

Copy `config/flexible-markets.example.yaml` to the ignored
`config/flexible-markets.yaml`, customize it privately, and validate a live aggregate-only dry run:

```bash
flyclub-flexible-market --config config/flexible-markets.yaml --dry-run
```

For private deployment, set `FLYCLUB_FLEXIBLE_MARKETS_YAML` to the complete private YAML. Never
commit the real markets or run this production workflow in the public source repository; keep the
active schedule and personal configuration in the private deployment repository.

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

Only the synthetic `config/routes.example.yaml` and `config/flexible-markets.example.yaml` files
are versioned.

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

Do not place private itinerary data in GitHub Actions inputs on a public repository because run
metadata and logs may be public. The owner's scheduled and manual production workflows run from a
separate private deployment repository after the public split.

Report vulnerabilities privately according to [SECURITY.md](SECURITY.md). Public-release gates,
credential rotation, history scanning, and the private deployment boundary are documented in
[docs/PUBLICATION.md](docs/PUBLICATION.md).

## Disclaimer

Fly Club uses an unofficial provider integration and may stop working when upstream behavior
changes. Prices, availability, baggage, fare rules, passenger inventory, and booking conditions
must be confirmed directly with the seller before purchase. Fly Club does not buy tickets, provide
financial or travel advice, or guarantee that an observed fare remains available.

The project is not affiliated with or endorsed by Google, Google Flights, Telegram, Supabase,
Healthchecks.io, or GitHub.

## Contributing and acknowledgements

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change and
[ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for the open-source components used by Fly Club.

## License

Fly Club is available under the [MIT License](LICENSE).

## V1 scope

The V1 uses Python, the `fli` Google Flights provider, PostgreSQL on Supabase, GitHub Actions,
Telegram, and pytest. It will not include a web interface, machine learning, or browser automation.

# Fly Club

[![CI](https://github.com/atos-og/flyclub-public/actions/workflows/ci.yml/badge.svg)](https://github.com/atos-og/flyclub-public/actions/workflows/ci.yml)
[![Secret scan](https://github.com/atos-og/flyclub-public/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/atos-og/flyclub-public/actions/workflows/secret-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fly Club was created to solve a personal need: monitoring flight prices for desired destinations
without opening travel websites every day and repeating the same searches.

The project turns that manual routine into an automatic radar. It collects prices over time, builds
its own historical baseline, identifies when a fare is genuinely unusual, and sends a message in a
chat app when an opportunity is worth the user's attention.

Fly Club is not a booking platform or a generic flight search engine. Its main question is more
specific:

> Has a genuinely exceptional fare appeared right now?

> **Status:** public preview under active development. The source code and security boundary are
> public; the production deployment, personal configuration, credentials, and operational logs are
> private. The formal V1 release is still subject to the documented statistical review.

## What Fly Club does

- Searches configured flight markets automatically.
- Stores successful, empty, and failed checks in PostgreSQL.
- Builds a comparable price history for each route and search configuration.
- Calculates P10, P50, P90, percentile rank, recorded low, recent movement, and trend.
- Produces a deterministic and explainable Deal Score from 0 to 100.
- Sends low-noise opportunity alerts instead of reporting every small price change.
- Searches nearby dates and rolling flexible-date markets without changing the main monitor.
- Sends a separate daily summary using prices already collected during the day.
- Tracks provider and workflow health so important failures do not remain silent.

The current monitor searches for one passenger. Every displayed fare is the total round-trip price
returned for that passenger, not a one-way estimate. Availability for additional passengers must
still be confirmed before purchase.

## More than a fixed price alert

A basic tracker usually checks whether a fare is below a fixed amount. Fly Club also checks whether
the current price is exceptional compared with observations for the same route, dates, passenger
count, cabin, currency, stop policy, and origin group.

The current observation never influences its own baseline. When a field that affects price
comparability changes, Fly Club creates a separate historical series instead of mixing incompatible
data.

The system becomes better informed as its history grows, but it does not use machine learning or an
LLM to score fares. The rules remain deterministic, testable, and explainable.

## Deal Score

Deal Score measures price quality, not travel urgency.

| Component | Weight |
| --- | ---: |
| Current price percentile | 40 |
| Discount versus historical median (P50) | 25 |
| Proximity to the lowest recorded price | 15 |
| Objective recent price drop | 10 |
| Multi-observation trend | 10 |
| **Total** | **100** |

Days until departure are intentionally excluded. A mediocre fare does not become a great deal only
because the trip is close.

Historical confidence is shown separately:

| Prior observations | Confidence |
| --- | --- |
| Fewer than 12 | Insufficient for a score-based alert |
| 12–30 | Low / provisional |
| 31–100 | Moderate |
| More than 100 | High |

Recent drop and trend are separate signals. Recent drop is a point-in-time comparison, while trend
describes behavior across several historical observations.

## Monitoring flows

### Fixed-date monitor

The main private deployment runs approximately every 90 minutes. It searches routes sequentially,
persists normalized observations, evaluates them against prior-only history, applies cooldown and
deduplication rules, and sends an alert only when the configured policy is satisfied.

### Rolling flexible-market radar

This flow looks for a fixed-duration trip anywhere inside a rolling date window. It searches the
provider calendar in bounded chunks and verifies only the strongest candidates with an exact
round-trip request.

It has separate tables, history, thresholds, cooldown, and alert formatting. It currently runs
twice a day in the private deployment and does not change the performance or alerts of the main
monitor.

### Nearby dates and discovery

Independent flows can compare nearby date combinations or monitor broader discovery markets. Their
histories use isolated keys, so they cannot contaminate the main route statistics.

### Daily summary

The daily summary reads prices that are already stored. It does not call the flight provider and
does not compete with opportunity alerts.

## How it works

```text
private configuration
        ↓
route and market planning
        ↓
provider adapter (fli / Google Flights)
        ↓
provider-neutral normalized results
        ↓
PostgreSQL history on Supabase
        ↓
statistics + trend + confidence + Deal Score
        ↓
alert policy + cooldown + deduplication
        ↓
chat notification
```

The provider integration is isolated behind Fly Club models. Provider-specific objects never enter
the analysis, persistence, or alert layers. This keeps a future provider replacement possible
without rewriting the complete application.

## Technology

- Python 3.12
- PostgreSQL on Supabase
- `fli` as the current Google Flights provider adapter
- Pydantic for strict configuration validation
- Psycopg for PostgreSQL access
- GitHub Actions for short-lived jobs and CI
- Telegram Bot API as the current chat-notification implementation
- Pytest and Ruff for automated quality checks
- Gitleaks and GitHub Secret Scanning for repository security

Money uses `Decimal` in Python and `NUMERIC` in PostgreSQL. Binary floating-point values are not
used for prices or monetary thresholds.

## Public source and private operation

This repository contains source code, tests, synthetic configuration examples, public CI, and inert
deployment templates only.

It does **not** contain:

- production credentials or API tokens;
- a real `.env` file;
- database connection strings;
- chat IDs;
- private healthcheck URLs;
- personal passenger information;
- private travel dates or complete itineraries;
- enabled production schedules;
- production logs or database contents.

The real monitor runs from a separate private repository. Deployment templates are stored under
[`examples/github-actions`](examples/github-actions) with the `.example.yml` suffix, so GitHub does
not execute them here.

A destination name may be intentionally public, but credentials, personal identifiers, complete
private itineraries, and operational data are never part of the public source.

See [the publication and deployment model](docs/PUBLICATION.md) and the
[security policy](SECURITY.md) for the complete boundary.

## Local setup

Requirements:

- Python 3.12 or newer
- Git
- PostgreSQL only when testing persistence locally

Create the environment and install the project:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create a private local configuration from the synthetic example:

```bash
cp config/routes.example.yaml config/routes.yaml
```

Windows PowerShell:

```powershell
Copy-Item config/routes.example.yaml config/routes.yaml
```

`config/routes.yaml` and `.env` are ignored by Git.

Validate the configuration:

```bash
flyclub
```

Perform a complete provider dry run without persistence or notifications:

```bash
flyclub --monitor --dry-run
```

Validate a rolling flexible-market configuration without persistence:

```bash
flyclub-flexible-market --config config/flexible-markets.yaml --dry-run
```

Apply PostgreSQL migrations and run the persisted monitor only after configuring credentials
outside Git:

```bash
flyclub-db-migrate
flyclub --monitor
```

Do not pass `DATABASE_URL` as a command argument or place it in shell history.

## Validation

Run the complete local validation:

```bash
pytest
ruff check .
ruff format --check .
python scripts/check_public_boundary.py
```

The repository-boundary check rejects tracked environment files, private/local configuration,
credential-like files, and unexpected active workflows. GitHub also runs full-history Gitleaks on
every branch push and pull request.

## Project structure

```text
src/flyclub/              application and domain code
src/flyclub/providers/    provider adapters
src/flyclub/analysis/     statistics, trends, and Deal Score
src/flyclub/alerts/       decisions, formatting, and delivery
src/flyclub/storage/      PostgreSQL repositories and migrations
config/                   synthetic public configuration examples
examples/github-actions/  inert private-deployment workflow templates
tests/                    automated regression and boundary tests
docs/                     architecture, decisions, status, and security model
```

## Current limitations

- The provider uses an unofficial Google Flights integration and may break when upstream behavior
  changes.
- A displayed fare is not an inventory guarantee for additional passengers.
- Prices, availability, fare conditions, baggage, seat selection, cancellation, and change rules
  must be confirmed with the seller before purchase.
- Fly Club identifies unusual current prices; it does not predict the future price of a ticket.
- Scheduled GitHub Actions jobs are approximate and can be delayed.
- There is no web interface in V1. The project is intentionally focused on the monitoring and
  intelligence pipeline.

## Road to V1

The public preview is available now. Before creating the formal V1 release, the project will finish
its 30-day shadow evaluation of the next Deal Score version, review production stability, repeat
the security audit, and validate the private deployment against the exact public revision.

Normal development continues publicly through protected branches and pull requests.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
Security concerns, possible credential exposure, or private-data incidents must be reported
privately according to [SECURITY.md](SECURITY.md), never through a public issue.

## Disclaimer

Fly Club does not buy tickets and does not guarantee that a fare will remain available. It is not
affiliated with or endorsed by Google, Google Flights, Telegram, Supabase, Healthchecks.io, or
GitHub.

## Acknowledgements and license

The project uses open-source components listed in [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
Fly Club is available under the [MIT License](LICENSE).

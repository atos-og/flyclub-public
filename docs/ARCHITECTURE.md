# Fly Club Architecture

## Current system

The implemented system validates configuration, expands it into provider-neutral routes, can
perform one explicit Google Flights search, and can orchestrate a complete sequential collection
cycle with optional PostgreSQL persistence:

```text
routes YAML or FLYCLUB_ROUTES_YAML
                  ↓
        config.load_config
                  ↓
        route_planner.plan_routes
                  ↓
     provider-neutral RouteDefinition
                  ↓
          Monitor Runner
                  ↓
       GoogleFlightsProvider → fli
                  ↓
 provider-neutral SearchOutcome / FlightOption
                  ↓
       PostgresRepository
                  ↓
 route_checks + price_snapshots
                  ↓
   prior-only history + last sent alert
                  ↓
 statistics → trend → Deal Score
                  ↓
       Alert Engine → alert_history
                  ↓
       Alert Coordinator → Telegram

 persisted fixed-date prices → Daily Summary → daily_summary_history → Telegram

private rolling-market YAML → Flexible Market Scanner → provider calendar chunks
                           → exact verification of top candidates
                           → flexible_market_checks → prior-only Deal Score
                           → isolated flexible alert history → Telegram
```

The CLI validates configuration, reports counts and a non-secret fingerprint, and can show route
endpoints only when explicitly requested. One option performs a detailed single-route search. The
monitor option searches every route sequentially and prints counters only; `--dry-run` omits all
database writes.

## Current modules

- `flyclub.config`: loads YAML from a GitHub Secret or ignored local file, validates it with
  Pydantic, and formats errors without echoing input values.
- `flyclub.route_planner`: expands origin groups × destinations and creates stable route keys.
  A dedicated planner shifts complete trips across six non-zero ±3-day offsets and includes the
  flexible-series kind in otherwise date-specific identities without changing existing main keys.
- `flyclub.models`: owns provider-neutral enums and immutable route, leg, option, and search
  outcome models. Money is represented by `Decimal`.
- `flyclub.providers.base`: defines the `FlightProvider` protocol.
- `flyclub.providers.google_flights`: creates round-trip `fli` filters, applies bounded retry,
  classifies errors, reads the documented outbound full-round-trip price, warns once per search
  when the return journey differs by more than 2%, normalizes results, and validates deep links.
- `flyclub.monitor`: runs provider searches sequentially, records every outcome, derives the run
  status, analyzes successful observations, defers fare decisions until same-run HOME comparisons
  are available, coordinates alerts, updates aggregate provider health, and attempts to close
  aborted persisted runs as failures.
- `flyclub.storage.migrations`: discovers checksum-protected SQL migrations, serializes migration
  execution with an advisory lock, and reads its connection only from `DATABASE_URL`.
- `flyclub.storage.postgres`: persists monitor runs, comparable routes, route checks, and normalized
  snapshots and alert delivery state atomically and idempotently; database errors are sanitized.
- `flyclub.analysis.statistics`: provides pure `Decimal` P10/P50/P90, percentile rank, recorded-low,
  sample-size, cold-start, and confidence calculations over a prior-only historical baseline.
- `flyclub.analysis.trend`: keeps a point-in-time 24-hour/last-alert drop distinct from a prior-only
  multi-observation trend based on adjacent historical median windows.
- `flyclub.analysis.deal_score`: calculates an explainable 0–100 score from percentile, median
  discount, recorded-low proximity, recent drop, and trend. Low-confidence scores are explicitly
  provisional, and travel urgency is excluded.
- `flyclub.analysis.evaluator`: loads the prior-only comparable series and last delivered alert,
  prefers a valid 24-hour drop reference with last alert as fallback, and runs the complete pure
  analysis pipeline after each persisted successful check. It also calculates a daily-median v2
  shadow score and persists it through a write-only path that alert code never reads.
- `flyclub.health`: owns provider-health status and notification state shared across boundaries.
- `flyclub.alerts.engine`: consolidates price target, new low, exceptional score, and significant
  drop into one confidence-aware, cooldown-protected SEND or SUPPRESS decision.
- `flyclub.alerts.formatter`: builds a short HTML-safe message from normalized route, itinerary,
  passenger-scoped total price, statistics, score, and alert reasons; validated offer URLs are
  hidden behind one compact clickable label, and missing URLs are never invented. It separately
  formats non-persistent two-passenger confirmations. The optional private confirmation-workflow
  URL enters at runtime and is never hardcoded into the package.
- `flyclub.alerts.telegram`: implements a sanitized standard-library client for the Telegram Bot
  API.
- `flyclub.alerts.service`: persists each consolidated decision, sends only a newly created `SEND`,
  and records Telegram delivery success or failure without resending an existing route check.
- `flyclub.alerts.health`: sends one warning after the configured consecutive-problem threshold and
  one recovery after a reported incident, with persistent deduplication and retry-on-failure state.
- `flyclub.main`: exposes configuration validation, explicit single-route search, and full monitor
  commands.
- `flyclub.manual_confirmation`: validates four explicit workflow inputs, performs one
  two-passenger search, and sends a clearly tagged Telegram result without persistence or analysis.
- `flyclub.date_matrix`: builds a bounded independent departure/return matrix for one explicit
  manual route, searches at most 49 combinations sequentially, ranks the three best normalized
  options, and explains savings and date shifts without persistence or alert-policy access.
- `flyclub.fare_risk`: validates two manually verified fare policies and their sources, calculates
  fixed cancellation/change exposure with `Decimal`, withholds recommendations for stale sources,
  and sends a non-persistent Telegram comparison without changing either quoted price.
- `flyclub.flexible_dates`: runs the normal persisted analysis/alert pipeline over isolated shifted
  fixed-duration routes without changing core provider-health notification state.
- `flyclub.discovery`: runs an optional manual-only market scan with isolated `DISCOVERY` keys and
  per-destination score thresholds, reusing persistence and alerts without provider-health updates.
- `flyclub.daily_summary`: reads only already-persisted fixed-date prices, formats one compact local
  day summary, claims an idempotent delivery date, and sends it through Telegram without entering
  the alert engine or calling a flight provider.
- `flyclub.flexible_market_config` and `flyclub.flexible_market_models`: validate a separate private
  rolling-market configuration, including optional fixed complete-trip windows, and expose
  provider-neutral calendar definitions and fares.
- `flyclub.providers.google_flights_flexible`: performs bounded sequential calendar chunks and exact
  verification, converting provider money to `Decimal` at the adapter boundary.
- `flyclub.flexible_market`: intersects rolling provider limits with any fixed complete-trip
  window, skips expired windows, partitions active dates into independently scored periods,
  verifies only the strongest candidates, and orchestrates isolated persistence and alerts.
- `flyclub.storage.flexible_market` and `flyclub.flexible_market_alerts`: maintain prior-only market
  histories, cooldown-safe decisions, and compact `GARIMPO FLEXÍVEL` Telegram delivery without
  reading or changing the main alert history.

## Component boundaries

- Configuration may describe personal trips but must not contain credentials.
- Route identity includes fields that determine whether histories are comparable; changing only an
  alert target does not create a new statistical route.
- Provider adapters must convert external results into `FlightOption` and `SearchOutcome` before
  returning. External provider types must not cross this boundary.
- `SearchOutcome` keeps empty results distinct from provider and request failures.
- Cross-origin decisions compare only compatible routes from the same run and subtract the
  explicitly configured positioning-cost estimate; no cost is inferred from provider data.

## V1 flow

Collection, PostgreSQL persistence, prior-only analysis, consolidated decisions, decision history,
and Telegram delivery are operational in the local monitor:

```text
Config → Route Planner → Monitor Runner → FlightProvider → GoogleFlightsProvider / fli
       → normalization → PostgreSQL → statistics/trend → Deal Score
       → Alert Engine → Telegram
```

The monitor runs as a short-lived GitHub Actions job approximately every 90 minutes. An external
`workflow_dispatch` is the intended primary trigger; native schedules run 30 minutes later as a
fallback and skip business work when a recent external run exists. It starts, collects, stores,
analyzes, optionally notifies, records health, and exits. The job is wrapped by one external
Healthchecks.io heartbeat:

The workflow cron is the single source of truth for deployment cadence. Route configuration does
not expose an interval field that the application cannot enforce.

```text
GitHub Actions job starts → Healthchecks /start
              ↓
       Fly Club main steps
              ↓
      job success? ── yes → Healthchecks success
              └────── no  → Healthchecks /fail
```

All three pings are bounded, best-effort `curl` requests. Healthchecks.io is not imported by the
Python application and does not influence provider health, analysis, persistence, alert decisions,
or route-level behavior. If the runner never starts, or a started job never reaches its completion
step, the missing success ping is detected externally after the configured period/grace window.

## Persistence

The initial PostgreSQL migration implements these principal entities:

- `monitored_routes`: versioned comparable route definitions.
- `monitor_runs`: start, finish, outcome, counters, and run error summary.
- `route_checks`: one result per route and run, including empty and failed checks.
- `price_snapshots`: normalized individual itinerary options.
- `alert_history`: consolidated alert decisions and Telegram delivery state.
- `deal_score_shadow`: versioned, idempotent v2 evaluations kept separate from alert decisions.
- `provider_health`: last success, consecutive problem runs, current incident, and recovery state.
- `daily_summary_history`: one idempotent Telegram delivery state per Brasília calendar date.
- `flexible_market_checks`: one confirmed best rolling-market observation per market/period/run,
  including unsuccessful outcomes and provider request counts.
- `flexible_market_alert_history`: isolated flexible-market decisions and Telegram delivery state.

The repository records one best valid route price per `route_check`, not every returned itinerary,
while retaining all normalized options in `price_snapshots`. Its history query requires the current
check ID and excludes it from the returned baseline. Provider health records consecutive problem
runs, incident start, last success, recovery, and delivered problem/recovery notification markers.
Each route check receives at most one persisted alert decision; delivery progresses from `PENDING`
to `SENT` or `FAILED`, while suppressed decisions use `NOT_REQUESTED`. Both migrations and the
repository transitions were validated against a live Supabase PostgreSQL project with synthetic
data removed afterward.

## External integrations

- `fli`: implemented primary V1 source, pinned to the reviewed 0.10.0 Git commit because that
  release is not yet available from PyPI.
- Supabase PostgreSQL through `psycopg`: provisioned, migrated, and validated with idempotent
  migrations and complete synthetic persistence/cleanup smoke tests.
- Telegram Bot API: configured, live-tested, and connected to idempotent monitor delivery.
- GitHub Actions: the least-privilege, non-overlapping monitor accepts manual/external dispatches
  and retains duplicate-safe native fallback schedules 30 minutes later. CI separately validates
  pushes and pull requests. A separate daily workflow reads persisted prices and sends the
  informational summary without provider calls or alert-policy access. Two additional manual-only
  workflows compare nearby date combinations and verified fare rules; they require only Telegram
  secrets and do not access PostgreSQL or private route configuration.
- Healthchecks.io: one external dead-man check wraps the main monitor workflow with start,
  success, and failure signals. Its private base Ping URL is read only from the
  `HEALTHCHECKS_PING_URL` Repository Secret; native Healthchecks.io Telegram delivery reports
  workflow availability independently of Fly Club's bot.

Provider health inside the application and run health in PostgreSQL remain authoritative for
captured business/provider incidents. Healthchecks.io represents only whether the scheduled
process continues to start and finish.

The date matrix and fare-risk comparison are decision-support side flows. The first calls the
existing provider sequentially for one explicit route and sends only a point-in-time top three.
The second performs no provider or web request; it analyzes explicit rules and source metadata
supplied for two quotes. Neither reads or writes PostgreSQL, provider health, Deal Score, alert
history, cooldown state, or the automatic schedules.

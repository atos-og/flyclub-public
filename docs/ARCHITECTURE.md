# Fly Club Architecture

## Current system

The implemented system validates configuration, expands it into provider-neutral routes, can
perform one explicit Google Flights search, and has an independent PostgreSQL persistence layer:

```text
routes YAML or FLYCLUB_ROUTES_YAML
                  ↓
        config.load_config
                  ↓
        route_planner.plan_routes
                  ↓
     provider-neutral RouteDefinition
                  ↓
       GoogleFlightsProvider → fli
                  ↓
 provider-neutral SearchOutcome / FlightOption

RouteDefinition + SearchOutcome
                  ↓
       PostgresRepository
                  ↓
 route_checks + price_snapshots
```

The CLI validates configuration, reports counts and a non-secret fingerprint, and can show route
endpoints only when explicitly requested. A separate explicit option performs one live route
search. The repository and migration CLI exist, but the search CLI does not persist results yet.

## Current modules

- `flyclub.config`: loads YAML from a GitHub Secret or ignored local file, validates it with
  Pydantic, and formats errors without echoing input values.
- `flyclub.route_planner`: expands origin groups × destinations and creates stable route keys.
- `flyclub.models`: owns provider-neutral enums and immutable route, leg, option, and search
  outcome models. Money is represented by `Decimal`.
- `flyclub.providers.base`: defines the `FlightProvider` protocol.
- `flyclub.providers.google_flights`: creates round-trip `fli` filters, applies bounded retry,
  classifies errors, normalizes results, and validates deep links.
- `flyclub.storage.migrations`: discovers checksum-protected SQL migrations, serializes migration
  execution with an advisory lock, and reads its connection only from `DATABASE_URL`.
- `flyclub.storage.postgres`: persists monitor runs, comparable routes, route checks, and normalized
  snapshots atomically and idempotently; database errors are sanitized.
- `flyclub.main`: exposes configuration validation and explicit single-route search.

## Component boundaries

- Configuration may describe personal trips but must not contain credentials.
- Route identity includes fields that determine whether histories are comparable; changing only an
  alert target does not create a new statistical route.
- Provider adapters must convert external results into `FlightOption` and `SearchOutcome` before
  returning. External provider types must not cross this boundary.
- `SearchOutcome` keeps empty results distinct from provider and request failures.

## Planned V1 flow

The agreed V1 direction is shown below, but components after `FlightProvider` are not implemented
and must not be treated as operational:

```text
Config → Route Planner → Monitor Runner → FlightProvider → GoogleFlightsProvider / fli
       → normalization → PostgreSQL → statistics/trend → Deal Score
       → Alert Engine → Telegram
```

The monitor will run as a short-lived GitHub Actions job approximately every three hours. It will
start, collect, store, analyze, optionally notify, record health, and exit.

## Persistence

The initial PostgreSQL migration implements these principal entities:

- `monitored_routes`: versioned comparable route definitions.
- `monitor_runs`: start, finish, outcome, counters, and run error summary.
- `route_checks`: one result per route and run, including empty and failed checks.
- `price_snapshots`: normalized individual itinerary options.
- `alert_history`: consolidated alert decisions and Telegram delivery state.
- `provider_health`: last success, consecutive problem runs, current incident, and recovery state.

The repository records one best valid route price per `route_check`, not every returned itinerary,
while retaining all normalized options in `price_snapshots`. Its history query requires the current
check ID and excludes it from the returned baseline. No live Supabase database has been connected
or migrated yet.

## External integrations

- `fli`: implemented primary V1 source, pinned to the reviewed 0.10.0 Git commit because that
  release is not yet available from PyPI.
- Supabase PostgreSQL through `psycopg`: schema, migration runner, and repository implemented;
  external database provisioning and live validation are pending.
- Telegram Bot API: accepted notification channel, not implemented yet.
- GitHub Actions: accepted scheduler and runner, workflow not implemented yet.
- External dead-man switch: proposed to detect missing GitHub Actions executions; not accepted as
  operational until configured by the user.

Provider health inside the application and run health in PostgreSQL remain required even if an
external dead-man switch is later enabled.

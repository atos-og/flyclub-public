# Fly Club Architecture

## Current system

The implemented system currently validates configuration and expands it into provider-neutral
route definitions:

```text
routes YAML or FLYCLUB_ROUTES_YAML
                  ↓
        config.load_config
                  ↓
        route_planner.plan_routes
                  ↓
     provider-neutral RouteDefinition objects
```

The CLI validates configuration, reports counts and a non-secret fingerprint, and can show route
endpoints only when explicitly requested. It does not search or persist flights yet.

## Current modules

- `flyclub.config`: loads YAML from a GitHub Secret or ignored local file, validates it with
  Pydantic, and formats errors without echoing input values.
- `flyclub.route_planner`: expands origin groups × destinations and creates stable route keys.
- `flyclub.models`: owns provider-neutral enums and immutable route, leg, option, and search
  outcome models. Money is represented by `Decimal`.
- `flyclub.providers.base`: defines the `FlightProvider` protocol. No live provider exists yet.
- `flyclub.main`: exposes the current configuration-validation CLI.

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

## Planned persistence

No database schema exists yet. The accepted principal entities are:

- `monitored_routes`: versioned comparable route definitions.
- `monitor_runs`: start, finish, outcome, counters, and run error summary.
- `route_checks`: one result per route and run, including empty and failed checks.
- `price_snapshots`: normalized individual itinerary options.
- `alert_history`: consolidated alert decisions and Telegram delivery state.
- `provider_health`: last success, consecutive problem runs, current incident, and recovery state.

Statistics will use one best valid route price per `route_check`, not every returned itinerary.
The current check will be excluded from the historical distribution used to evaluate it.

## External integrations

- `fli`: accepted primary V1 source, not implemented yet.
- Supabase PostgreSQL through `psycopg`: accepted persistence, not implemented yet.
- Telegram Bot API: accepted notification channel, not implemented yet.
- GitHub Actions: accepted scheduler and runner, workflow not implemented yet.
- External dead-man switch: proposed to detect missing GitHub Actions executions; not accepted as
  operational until configured by the user.

Provider health inside the application and run health in PostgreSQL remain required even if an
external dead-man switch is later enabled.


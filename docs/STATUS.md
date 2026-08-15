# Fly Club Status

## Current phase

Phase 14 complete — passenger-scoped fare monitoring operational.

## Done

- Private Git repository cloned with `main` as the initial branch.
- Python 3.12 `src/` package skeleton and `flyclub` CLI created.
- Strict YAML configuration models with sanitized validation errors.
- Personal `config/routes.yaml`, `.env`, virtual environments, and secrets ignored by Git.
- Public `config/routes.example.yaml` with BH and São Paulo origin semantics.
- Route Planner expands two origin groups × three destinations into six comparable routes.
- Provider-neutral route, leg, option, outcome, status, and `FlightProvider` models created.
- Empty provider results are modeled separately from failures.
- Persistent guidance, architecture, decision, and operational status documents created.
- Foundation and persistent guidance committed and pushed to private `main`.
- `fli` 0.10.0 source pinned to a reviewed immutable Git commit.
- The `fli` adapter now uses the documented outbound journey price as the complete round-trip
  total and emits at most one sanitized warning per search when the final journey differs by more
  than 2%.
- A non-persistent diagnostic sampled 30 real provider requests and 716 comparable options: 170
  options diverged, with 0.7968% mean absolute difference and a 38.6118% maximum, confirming that
  the previous final-journey field was not a safe round-trip total.
- `GoogleFlightsProvider` builds round-trip searches with explicit airport groups.
- Provider results normalize to `Decimal` prices and provider-neutral legs/options.
- Empty, invalid, temporary failure, provider format change, and success outcomes are distinct.
- Bounded retry with exponential backoff is implemented at the provider boundary.
- Google Flights URLs are accepted only when they are valid HTTP(S) URLs.
- A controlled CLI option can search exactly one configured route.
- A real public-example CNF → LIS round-trip search returned five BRL options and deep links.
- PR #1 was validated, marked ready, and squash-merged into `main`.
- `psycopg` PostgreSQL support added without an ORM.
- Checksum-protected migration discovery and an advisory-locked migration CLI implemented.
- Initial schema created for routes, runs, checks, snapshots, alert history, and provider health.
- Monetary columns use `NUMERIC(12, 2)` and Python writes preserve `Decimal` values.
- Route-check writes are atomic and idempotent on `(run, route, provider)`.
- Successful checks store the best price separately from ranked normalized itinerary snapshots.
- Historical best-price queries require and exclude the current route-check ID.
- Repository database errors are sanitized so connection details are not echoed.
- PR #2 was validated and squash-merged into `main`.
- The monitor runner searches configured routes sequentially through `FlightProvider`.
- Every success, empty result, classified failure, and unexpected adapter failure is accounted for.
- Persisted runs receive deterministic `SUCCESS`, `PARTIAL`, or `FAILURE` status and counters.
- Aborted persisted cycles attempt a final failure update while preserving the original error.
- `--monitor --dry-run` exercises all provider calls without requiring or writing a database.
- Monitor summaries omit route endpoints, dates, prices, and booking URLs.
- PR #3 was validated and squash-merged into `main`.
- A Supabase Free PostgreSQL project was connected through its Session Pooler.
- Migration `001_initial` was applied once and an immediate rerun applied zero migrations.
- Live synthetic persistence created one run, route check, and snapshot with correct relationships.
- The live history query excluded the current observation, and all synthetic rows were cleaned up.
- Local CLIs load ignored `.env` values without overriding external environment variables.
- Provider health derives `HEALTHY`, `DEGRADED`, `UNAVAILABLE`, and `PROVIDER_CHANGED` per run.
- Live health transitions preserved incident start and consecutive failures, recorded recovery, and
  cleaned up the synthetic health row.
- PR #5 was validated and merged into `main`.
- The ignored real route configuration was created and validated without entering Git history.
- A complete real dry run succeeded for every planned route, followed by a successful persisted
  collection cycle in Supabase.
- Pure `Decimal` statistics now calculate P10, P50, P90, percentile rank, recorded low, sample size,
  cold-start state, and configurable confidence.
- Percentile rank gives tied prices half weight, and the current price remains outside its own
  historical baseline.
- PR #6 was validated and squash-merged into `main`.
- Deal Score weights are configurable and total 100: percentile 40, median discount 25,
  recorded-low proximity 15, recent drop 10, and trend 10.
- Days until departure is excluded from Deal Score and reserved for a future Buy Signal/Forecast.
- Recent drop is a typed point-in-time comparison against 24 hours or the last alert; trend uses
  two prior-only multi-observation median windows so the current drop is not counted twice.
- Scores require at least 12 prior observations; low-confidence results are marked provisional.
- Every score exposes its component points, maximums, metrics, confidence, and classification.
- PR #7 was validated and squash-merged into `main`.
- Persisted successful checks now load chronological prior observations while explicitly excluding
  the current check, then calculate statistics, trend, recent drop, and Deal Score.
- A close 24-hour observation is preferred for recent drop; the last successfully delivered alert
  is a typed fallback when no suitable 24-hour reference exists.
- Persisted monitor summaries include only the safe aggregate count of analyzed routes.
- A real integrated cycle successfully collected, persisted, and analyzed every planned route.
- Pure alert decisions consolidate price target, new low, exceptional score, and significant drop.
- Manual targets work during cold start; statistical triggers require minimum history.
- Low-confidence exceptional scores require independent corroboration before sending.
- Significant drops require both configured absolute and percentage thresholds.
- Cooldown suppresses repetition unless the fare falls significantly again.
- The compact plain-text formatter shows route, price, monetary and percentage savings, historical
  position in plain language, recorded low, alert reasons, actionable positioning economics, and
  only a validated provider URL when one exists.
- The alert price line explicitly labels the configured passenger count with correct singular or
  plural wording, preventing a one-passenger total from being mistaken for a group total.
- A separate manually dispatched workflow confirms one explicit itinerary for exactly two Economy
  passengers, sends the total and per-person amount to Telegram, and never persists or analyzes the
  result. Automatic alerts scoring at least 80 with moderate/high confidence link to this check.
- A separate flexible-date workflow shifts the complete trip across six non-zero ±3-day offsets in
  two daily 24-route shards, avoiding one long 48-route job while keeping provider calls sequential.
  Each pair receives one daily observation in an isolated `FLEXIBLE` route key, reuses
  persistence/analysis/alerts, omits core provider-health updates, and prefixes Telegram messages
  with `🗓️ DATA FLEXÍVEL`.
- Thirty optional discovery routes now cover 15 curated destinations from BH and São Paulo with
  isolated `DISCOVERY` histories, 60-point Americas/Brazil and 90-point Europe thresholds, and
  `🔎 DESCOBERTA` messages. The workflow is manual-only pending explicit schedule-cost approval.
  A proposed three-runs-per-week schedule would add about 13 runs/month; using the observed route
  timings, the conservative estimate is 6–12 minutes/run and 78–156 Actions minutes/month, plus
  390 route checks and up to 1,950 snapshots/month.
- Deal Score `daily-median-v2` now runs in write-only shadow mode beside v1. It reduces each
  Brasília calendar day to one median, persists versioned metrics in `deal_score_shadow`, and has no
  code path into alert decisions or Telegram. The first persisted row starts a 30-day observation
  window documented in `docs/deal-score-v2-shadow.md`; promotion is explicitly manual.
- A private passenger-count change generated new comparable route keys while retaining the prior
  series separately; no historical prices crossed the comparability boundary.
- The first production dispatch after that change completed in 1m54s with eight successful and
  analyzed routes, eight cold-start suppressions, zero empty/failed routes, and zero alerts.
- A minimal sanitized Telegram Bot API client is implemented with no additional dependency and no
  credential values in code or logs.
- The private Telegram bot and chat were configured through the ignored `.env`, and one controlled
  live delivery succeeded.
- Every successful persisted route check now receives one idempotent consolidated alert decision.
- New `SEND` decisions are formatted and delivered once; `SENT`, `FAILED`, and `NOT_REQUESTED`
  delivery states are persisted in `alert_history`.
- Existing route-check decisions are never resent, and monitor output reports only aggregate sent
  and suppressed counters.
- A complete live cycle collected and analyzed eight routes, persisted eight suppressions, and sent
  no itinerary alert during cold start.
- Least-privilege CI and monitor workflows use Python 3.12 and immutable full-SHA official actions.
- The monitor schedule avoids the top of the hour, prevents overlapping runs, validates required
  secret presence, applies migrations, and supports manual dispatch.
- The four private GitHub Secrets were configured without exposing their values.
- CI passed on GitHub, and the first manual monitor dispatch completed in 1m45s with eight
  successful routes, eight analyses, eight suppressions, and zero failures.
- Provider health warnings become eligible after three consecutive problem runs by default.
- Problem and recovery notifications have persistent sent markers, do not repeat, and remain
  eligible for retry when Telegram delivery fails.
- Migration `002_provider_health_notifications` was applied once and its immediate rerun applied
  zero migrations.
- Live synthetic provider-health transitions validated three consecutive failures, warning state,
  recovery state, deduplication, and cleanup without sending a real health message.
- Fare alert decisions now wait until every route is collected, while provider searches remain
  sequential.
- Positioning fares use only the best compatible HOME fare from the same run for context, regardless
  of origin order.
- POSITIONING markets now require a coarse configured round-trip cost estimate. Alert decisions use
  net savings after that cost, suppress candidates below the material threshold, and show gross
  savings, estimated cost, and estimated net savings when actionable.
- Savings context appears only above the configurable material threshold and never includes an
  invented BH-to-São-Paulo cost.
- A complete live cycle validated the deferred path with eight successes, eight analyses, eight
  cold-start suppressions, zero fare alerts, zero health alerts, and zero failures.
- The main monitor workflow now wraps its execution with one Healthchecks.io start and completion
  heartbeat, reporting `/fail` after fatal job failures through an `always()` final step.
- External pings are best effort with a ten-second timeout and five retries; their failure never
  blocks or changes the Fly Club job result.
- The private Ping URL is required only as the `HEALTHCHECKS_PING_URL` Repository Secret and no
  Healthchecks library, service, database, API, worker, or route-level check was added.
- Workflow contract tests verify ping order, bounded best-effort behavior, failure handling, secret
  sourcing, and absence of a committed Healthchecks endpoint.
- The private `HEALTHCHECKS_PING_URL` Repository Secret and one native Healthchecks.io Telegram
  integration were configured without exposing the Ping URL.
- PR #14 passed CI and was squash-merged into `main`.
- The first heartbeat-enabled manual production run completed in 1m31s: `/start`, eight successful
  and analyzed routes, eight suppressions, zero fare/health alerts, zero failures, and the final
  success ping all completed without runtime warnings.
- The production monitor schedule now runs every 90 minutes using alternating minute-17 and
  minute-47 UTC cron entries, preserving off-hour scheduling and non-overlap protection.
- The unused `monitor.interval_hours` YAML field was removed so the GitHub Actions cron is the sole
  source of truth for deployment cadence.
- The workflow accepts external/manual dispatches as the primary low-latency trigger and retains
  native schedules 30 minutes later as duplicate-safe fallbacks. A fallback skips all provider,
  database, Telegram, and Healthchecks work after a recent successful or active external run.
- A public setup guide documents a repository-only fine-grained `Actions: write` token kept in the
  external scheduler, two grouped cron-job.org jobs covering all 16 Brasília times, validation,
  rotation, and fallback behavior without committing credentials.
- The Healthchecks.io `Fly Club Monitor` check now uses a 90-minute Simple period with the existing
  one-hour grace window, verified in the account after the workflow deployment.
- PR #17 passed CI and was squash-merged into `main`; the remote workflow exposes both alternating
  cron entries on the default branch.

## In progress

- None.

## Next

- Perform the dedicated V1 security, documentation, license, and acknowledgements review before
  considering public visibility.

## Known issues

- The user's system Python is not currently available on PATH; development validation used the
  local `.venv` created from the Codex Python 3.12 runtime.

## Last validation

Date: 2026-08-15

Tests:

- `pytest --cov=flyclub --cov-report=term-missing`: 177 passed, 91% total coverage, including the
  Deal Score v2 isolation regression.
- `ruff check .`: passed.
- `ruff format --check .`: passed after formatting.
- `python -m pip check`: passed.
- `git diff --check`: passed.
- Monitor workflow YAML parsing and heartbeat contract tests: passed.
- Monitor 90-minute schedule contract test: passed.

Manual checks:

- `flyclub --config config/routes.example.yaml --show-routes`: passed and planned six routes.
- `flyclub --config config/routes.example.yaml --search-route from_bh:LIS`: live provider search
  succeeded with five BRL round-trip options and valid Google Flights deep links.
- `.venv`, `.env`, and `config/routes.yaml`: confirmed ignored by Git.
- Repository scan found no committed credential values.
- `flyclub-db-migrate` without `DATABASE_URL`: failed safely without exposing a value.
- Migration discovery found the bundled `001_initial.sql`; no live PostgreSQL engine was available
  for an integration test.
- `flyclub --config config/routes.example.yaml --monitor` without `DATABASE_URL`: failed safely
  before any provider call.
- Live Supabase migration: one migration applied; immediate rerun applied zero.
- Live synthetic persistence: run/check/snapshot each verified once; current observation excluded;
  exact synthetic records removed afterward.
- Live synthetic provider health: consecutive problems, incident, recovery, and cleanup verified.
- `flyclub-db-migrate` loaded `DATABASE_URL` from ignored `.env` and applied zero pending migrations.
- Private configuration validation planned eight routes without printing their endpoints.
- Real provider dry run: eight successful routes, zero empty results, and zero failures.
- First real persisted cycle: eight successful routes, zero empty results, and zero failures.
- Integrated persisted analysis cycle: eight successful and analyzed routes, zero empty results,
  and zero failures; cold-start sample sizes correctly produced no statistically eligible score.
- Controlled Telegram delivery: one sanitized test message was accepted by the configured bot.
- Integrated alert cycle: eight successful and analyzed routes, eight persisted `SUPPRESS` /
  `NOT_REQUESTED` decisions, zero delivery attempts, and zero failures.
- GitHub CI: first pull-request run passed in 33 seconds.
- GitHub Actions production dispatch: migrations zero, eight successful/analyzed routes, eight
  suppressions, zero price alerts, zero failures, completed in 1m45s.
- Live migration 002: one migration applied; immediate rerun applied zero.
- Live synthetic provider-health notifications: problem/recovery markers and retry-safe transitions
  passed; the exact synthetic row was removed.
- Integrated same-run comparison cycle: eight successful/analyzed routes, eight suppressions, zero
  fare/health alerts, and zero failures.
- GitHub Actions heartbeat production dispatch: start and completion steps succeeded, the persisted
  monitor completed eight of eight routes successfully, and no runtime warning was emitted.
- GitHub Actions remote workflow: alternating 90-minute cron entries verified on `main` after PR
  #17 merged.
- Healthchecks.io `Fly Club Monitor`: 90-minute period and one-hour grace time verified in the
  authenticated account.
- Passenger-scoped production validation: eight new isolated series received one successful
  observation each, with provider health remaining `HEALTHY` and no notification sent.
- Round-trip price diagnostic: 30 live requests completed without persistence; 716 option pairs
  compared, 170 divergences, 0.7968% mean absolute difference, and 38.6118% maximum difference.
- Live migration 003: one migration applied; the workflow immediately confirmed zero pending
  migrations.
- Deal Score v2 production shadow validation: one main workflow run completed in 1m57s with seven
  successful/analyzed routes, one empty route, zero failures, seven suppressed alerts, and seven
  isolated `daily-median-v2` rows. The first row was recorded on 2026-08-15; the earliest 30-day
  review is 2026-09-14.
- The private routes Secret was re-uploaded as raw UTF-8 after Windows PowerShell 5.1 transcoding
  was found and diagnosed; the following GitHub Actions run parsed it successfully.
- First flexible-date production shard: 24 independent routes completed in 4m58s; 22 were
  successful/analyzed, two were empty, none failed, and all 22 alert decisions were suppressed.
- Personal travel dates that had been reused as inert manual-confirmation test fixtures were
  replaced with synthetic dates and airports in the current tree. Historical commit sanitation is
  pending an explicit history-rewrite decision while the repository remains private.

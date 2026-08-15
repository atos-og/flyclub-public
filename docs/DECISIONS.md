# Fly Club Decisions

Only material product and architecture decisions belong here.

## DEC-001 — `fli` is the primary V1 provider

Status: Accepted

Context: Fly Club needs lightweight Google Flights-oriented results on ephemeral GitHub runners.

Decision: Use `fli` first; do not use Playwright, Amadeus, or SerpApi in V1. Pin the reviewed
0.10.0 source commit until an equivalent release is published to PyPI.

Reason: It is Python-native, avoids a browser, and supports the required search shape.

Trade-offs: It relies on an unofficial Google interface, can break when upstream formats change,
and currently requires installing a fixed Git dependency.

## DEC-002 — Providers are isolated from the domain

Status: Accepted

Context: The initial provider is unofficial and may need replacement or fallback later.

Decision: Application code consumes Fly Club's `FlightProvider`, `SearchOutcome`, and normalized
models. Provider-specific imports stay inside the adapter.

Reason: A new provider must not require rewriting storage, analysis, or alerts.

Trade-offs: Normalization requires explicit mapping and may leave unsupported fields null.

## DEC-003 — PostgreSQL on Supabase with `psycopg`

Status: Accepted

Context: GitHub Actions runners are ephemeral, while all observations must survive each run.

Decision: Use PostgreSQL on Supabase through a Postgres-native `psycopg` repository. Store the
connection string only as `DATABASE_URL` in secrets.

Reason: This provides durable storage, transactions, SQL analytics, and portability without an ORM.

Trade-offs: Supabase Free has storage, availability, and backup limitations that must be monitored.

## DEC-004 — Short-lived GitHub Actions execution

Status: Accepted

Context: The monitor only needs to wake periodically and must not depend on the user's computer.

Decision: Run approximately every 90 minutes and support manual dispatch; do not operate a 24/7
server.

Reason: It halves the polling detection window while remaining compatible with the R$ 0 goal and
the observed GitHub Actions allowance.

Trade-offs: Schedules are approximate and require independent monitoring to detect missed runs.
The higher request rate also modestly increases unofficial-provider reliability risk and storage
growth.

An external `workflow_dispatch` scheduler may be used as the primary trigger to reduce queue
latency. Native schedules remain 30-minute-delayed fallbacks and skip provider/database work after
a recent external run. The external credential is a repository-scoped fine-grained token held only
by the scheduler, because a GitHub Repository Secret cannot authenticate a caller outside a
workflow.

## DEC-005 — Route checks and snapshots are separate

Status: Accepted

Context: A provider request can succeed with several options, return empty, or fail.

Decision: Record one `route_check` per route/run and store normalized options separately as
`price_snapshots`.

Reason: This preserves execution truth without inventing prices for empty or failed searches.

Trade-offs: Persistence and queries have one additional relationship.

## DEC-006 — One best route price per run forms the statistical series

Status: Accepted

Context: Using every option would overweight runs that return more itineraries.

Decision: Compute historical percentiles from the best valid price of each comparable route check.

Reason: Each monitoring time receives equal statistical weight.

Trade-offs: Alternative itineraries remain available for detail but do not affect the baseline.

## DEC-007 — Exact decimal money

Status: Accepted

Context: Alert thresholds and price drops require reliable comparisons.

Decision: Use `Decimal` in Python and `NUMERIC` in PostgreSQL; never use binary floating point.

Reason: Avoid rounding drift in monetary rules and deduplication boundaries.

Trade-offs: Serialization and provider normalization must be explicit.

## DEC-008 — Statistical, explainable intelligence without ML

Status: Accepted

Context: V1 has no historical dataset suitable for forecasting and must remain understandable.

Decision: Use P10/P50/P90, percentile rank, simple trends, confidence, and a deterministic Deal
Score. Exclude the current observation from its evaluation baseline.

Reason: This answers whether a price is exceptional now without opaque model decisions.

Trade-offs: It does not predict future price direction; forecasting remains a later product.

## DEC-009 — Telegram only and no frontend in V1

Status: Accepted

Context: The product is a personal alert radar, not a general travel application.

Decision: Telegram is the sole V1 channel. Do not build a web UI, API server, or dashboard.

Reason: It minimizes cost, operations, security surface, and implementation scope.

Trade-offs: History is inspected through database and logs until a future product decision.

## DEC-010 — Private-first, public-ready repository

Status: Accepted

Context: The repository contains a portfolio project but personal travel data must stay private.

Decision: Develop privately while versioning only example configuration and secret names. Perform a
dedicated security, documentation, license, and acknowledgement review before making it public.

Reason: The Git history should be publishable without secret removal or rewriting.

Trade-offs: Real configuration must be supplied locally or through GitHub Secrets.

## DEC-011 — External dead-man switch

Status: Accepted

Context: In-process health monitoring cannot report that GitHub Actions failed to start at all.

Decision: Use one Healthchecks.io check named `Fly Club Monitor` on a Simple 90-minute period with
one-hour grace time. The main GitHub Actions job sends best-effort start, success, and failure
signals with bounded `curl` requests. Store the base Ping URL only in the
`HEALTHCHECKS_PING_URL` Repository Secret and use Healthchecks.io's native Telegram integration.
Do not connect the service to routes, provider-health classification, analysis, Deal Score,
persistence, or Fly Club alert decisions.

Reason: It closes the silent-failure gap outside the Fly Club process while preserving a narrow,
low-coupling boundary and the R$ 0 operating target.

Trade-offs: It adds an external account and a private endpoint, and GitHub or Healthchecks outages
can still delay signals. Best-effort pings avoid turning that external dependency into a cause of
monitor failure.

## DEC-012 — Deal Score excludes travel urgency

Status: Accepted

Context: Days until departure may affect purchase urgency, but do not make an otherwise median fare
more exceptional. Recent drop and trend can also double-count the same movement if both use the
current observation.

Decision: Score only price quality with configurable weights: percentile 40, discount versus P50
25, proximity to the recorded low 15, objective recent drop 10, and prior-history trend 10. Keep
days until departure outside Deal Score for a future Buy Signal/Forecast. Calculate a provisional,
low-confidence score from 12–30 prior observations, moderate confidence from 31–100, and high
confidence above 100. Recent drop compares the current price with a typed 24-hour or last-alert
reference; trend compares two multi-observation historical median windows excluding the current
price.

Reason: This keeps the score focused, deterministic, explainable, and prevents urgency or one
current movement from being rewarded twice.

Trade-offs: Low-sample scores remain useful but must be displayed and handled as provisional. A
separate future signal will be needed to express purchase timing or forecast urgency.

## DEC-013 — Low-confidence and cooldown alert safeguards

Status: Accepted

Context: A high provisional score or an unchanged low fare can otherwise produce noisy alerts,
especially early in a route's history.

Decision: Permit a manual price target during cold start. Require the configured minimum history
for statistical new-low and exceptional-score triggers. A low-confidence exceptional score cannot
send alone and needs corroboration from a new low, manual target, or significant drop. Significant
drop must satisfy both absolute and percentage thresholds. Cooldown suppresses repeated alerts
unless a new significant drop occurs; multiple reasons consolidate into one decision.

Reason: Confidence must affect notification weight, and repeated observations must not become
repeated messages.

Trade-offs: Conservative gating can delay some genuine early opportunities, while post-cooldown
reminders can still repeat an opportunity that remains valid.

## DEC-014 — Same-run HOME context for positioning fares

Status: Accepted

Context: A São Paulo-origin fare can look cheaper while still requiring separate travel from Belo
Horizonte, and historical or stale comparisons would make the alert misleading.

Decision: After sequential collection, defer fare-alert decisions until all successful routes in
the run are available. Compare a positioning fare only with the cheapest compatible HOME-origin
fare from that same run. Show the difference only above a configurable material-savings threshold,
and always preserve the positioning warning without estimating the separate trip cost.

Reason: This gives actionable context without mixing incompatible tickets or inventing costs.

Trade-offs: Fare decisions occur at the end of the collection cycle, and no comparison is shown if
the matching HOME route is empty or fails.

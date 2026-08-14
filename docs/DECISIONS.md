# Fly Club Decisions

Only material product and architecture decisions belong here.

## DEC-001 — `fli` is the primary V1 provider

Status: Accepted

Context: Fly Club needs lightweight Google Flights-oriented results on ephemeral GitHub runners.

Decision: Use `fli` first; do not use Playwright, Amadeus, or SerpApi in V1.

Reason: It is Python-native, avoids a browser, and supports the required search shape.

Trade-offs: It relies on an unofficial Google interface and can break when upstream formats change.

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

Decision: Run approximately every three hours and support manual dispatch; do not operate a 24/7
server.

Reason: It is simple and compatible with the R$ 0 goal.

Trade-offs: Schedules are approximate and require independent monitoring to detect missed runs.

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

Status: Proposed

Context: In-process health monitoring cannot report that GitHub Actions failed to start at all.

Decision: Consider a zero-cost external heartbeat with Telegram integration after the monitor
workflow exists.

Reason: It closes the silent-failure gap outside the Fly Club process.

Trade-offs: It adds an external service and private ping URL, so user approval is required.


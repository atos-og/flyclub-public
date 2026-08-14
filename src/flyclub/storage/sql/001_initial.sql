CREATE TABLE monitored_routes (
    id UUID PRIMARY KEY,
    route_key TEXT NOT NULL UNIQUE,
    origin_group TEXT NOT NULL,
    origin_label TEXT NOT NULL,
    origin_role TEXT NOT NULL CHECK (origin_role IN ('HOME', 'POSITIONING')),
    origin_airports TEXT[] NOT NULL CHECK (cardinality(origin_airports) > 0),
    positioning_notice TEXT,
    destination CHAR(3) NOT NULL,
    destination_name TEXT,
    departure_date DATE NOT NULL,
    return_date DATE NOT NULL CHECK (return_date > departure_date),
    passengers SMALLINT NOT NULL CHECK (passengers BETWEEN 1 AND 9),
    cabin TEXT NOT NULL CHECK (
        cabin IN ('ECONOMY', 'PREMIUM_ECONOMY', 'BUSINESS', 'FIRST')
    ),
    currency CHAR(3) NOT NULL,
    max_stops TEXT NOT NULL CHECK (
        max_stops IN ('ANY', 'NON_STOP', 'ONE_OR_FEWER_STOPS', 'TWO_OR_FEWER_STOPS')
    ),
    alert_price NUMERIC(12, 2) CHECK (alert_price > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    CHECK (origin_role <> 'POSITIONING' OR positioning_notice IS NOT NULL)
);

CREATE TABLE monitor_runs (
    id UUID PRIMARY KEY,
    config_fingerprint TEXT NOT NULL,
    provider TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILURE')),
    planned_routes INTEGER NOT NULL CHECK (planned_routes >= 0),
    successful_routes INTEGER NOT NULL DEFAULT 0 CHECK (successful_routes >= 0),
    empty_routes INTEGER NOT NULL DEFAULT 0 CHECK (empty_routes >= 0),
    failed_routes INTEGER NOT NULL DEFAULT 0 CHECK (failed_routes >= 0),
    error_code TEXT,
    error_message TEXT,
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE route_checks (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES monitor_runs(id) ON DELETE CASCADE,
    route_id UUID NOT NULL REFERENCES monitored_routes(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'SUCCESS', 'EMPTY', 'TEMPORARY_FAILURE', 'PROVIDER_CHANGED', 'INVALID_REQUEST'
        )
    ),
    result_count INTEGER NOT NULL CHECK (result_count >= 0),
    best_price NUMERIC(12, 2) CHECK (best_price > 0),
    currency CHAR(3) NOT NULL,
    error_code TEXT,
    error_message TEXT,
    UNIQUE (run_id, route_id, provider),
    CHECK (
        (status = 'SUCCESS' AND result_count > 0 AND best_price IS NOT NULL)
        OR (status <> 'SUCCESS' AND result_count = 0 AND best_price IS NULL)
    )
);

CREATE TABLE price_snapshots (
    id UUID PRIMARY KEY,
    route_check_id UUID NOT NULL REFERENCES route_checks(id) ON DELETE CASCADE,
    option_rank SMALLINT NOT NULL CHECK (option_rank > 0),
    price NUMERIC(12, 2) NOT NULL CHECK (price > 0),
    currency CHAR(3) NOT NULL,
    stops SMALLINT CHECK (stops >= 0),
    duration_minutes INTEGER CHECK (duration_minutes > 0),
    booking_url TEXT,
    google_flights_url TEXT,
    itinerary_hash TEXT NOT NULL,
    legs JSONB NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    UNIQUE (route_check_id, option_rank),
    UNIQUE (route_check_id, itinerary_hash),
    CHECK (jsonb_typeof(legs) = 'array')
);

CREATE TABLE alert_history (
    id UUID PRIMARY KEY,
    route_id UUID NOT NULL REFERENCES monitored_routes(id) ON DELETE RESTRICT,
    route_check_id UUID NOT NULL UNIQUE REFERENCES route_checks(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('SEND', 'SUPPRESS')),
    deal_score SMALLINT CHECK (deal_score BETWEEN 0 AND 100),
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    delivery_status TEXT NOT NULL CHECK (
        delivery_status IN ('NOT_REQUESTED', 'PENDING', 'SENT', 'FAILED')
    ),
    telegram_message_id TEXT,
    sent_at TIMESTAMPTZ,
    error_code TEXT,
    CHECK (decision = 'SEND' OR delivery_status = 'NOT_REQUESTED')
);

CREATE TABLE provider_health (
    provider TEXT PRIMARY KEY,
    current_status TEXT NOT NULL CHECK (
        current_status IN ('HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'PROVIDER_CHANGED')
    ),
    last_attempt_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    consecutive_problem_runs INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_problem_runs >= 0),
    incident_started_at TIMESTAMPTZ,
    recovered_at TIMESTAMPTZ,
    last_error_code TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX route_checks_history_idx
    ON route_checks (route_id, checked_at DESC)
    WHERE status = 'SUCCESS';

CREATE INDEX monitor_runs_started_at_idx ON monitor_runs (started_at DESC);
CREATE INDEX price_snapshots_price_idx ON price_snapshots (route_check_id, price);
CREATE INDEX alert_history_route_created_idx ON alert_history (route_id, created_at DESC);

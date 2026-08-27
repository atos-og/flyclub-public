CREATE TABLE flexible_market_checks (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES monitor_runs(id) ON DELETE CASCADE,
    market_key TEXT NOT NULL,
    market_label TEXT NOT NULL,
    period_key TEXT NOT NULL,
    period_label TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('SUCCESS', 'EMPTY', 'TEMPORARY_FAILURE', 'PROVIDER_CHANGED', 'INVALID_REQUEST')
    ),
    provider_requests INTEGER NOT NULL CHECK (provider_requests >= 0),
    window_start DATE NOT NULL,
    window_end DATE NOT NULL CHECK (window_end >= window_start),
    origin_airports TEXT[] NOT NULL CHECK (cardinality(origin_airports) > 0),
    destination_airports TEXT[] NOT NULL CHECK (cardinality(destination_airports) > 0),
    trip_duration_days SMALLINT NOT NULL CHECK (trip_duration_days > 0),
    passengers SMALLINT NOT NULL CHECK (passengers BETWEEN 1 AND 9),
    cabin TEXT NOT NULL CHECK (
        cabin IN ('ECONOMY', 'PREMIUM_ECONOMY', 'BUSINESS', 'FIRST')
    ),
    max_stops TEXT NOT NULL CHECK (
        max_stops IN ('ANY', 'NON_STOP', 'ONE_OR_FEWER_STOPS', 'TWO_OR_FEWER_STOPS')
    ),
    minimum_deal_score SMALLINT NOT NULL CHECK (minimum_deal_score BETWEEN 0 AND 100),
    departure_date DATE,
    return_date DATE,
    arrival_airport CHAR(3),
    calendar_price NUMERIC(12, 2) CHECK (calendar_price > 0),
    best_price NUMERIC(12, 2) CHECK (best_price > 0),
    currency CHAR(3) NOT NULL,
    result_count INTEGER NOT NULL CHECK (result_count >= 0),
    stops SMALLINT CHECK (stops >= 0),
    duration_minutes INTEGER CHECK (duration_minutes > 0),
    booking_url TEXT,
    google_flights_url TEXT,
    itinerary_hash TEXT,
    legs JSONB,
    sample_size INTEGER CHECK (sample_size >= 0),
    confidence TEXT CHECK (confidence IN ('INSUFFICIENT', 'LOW', 'MODERATE', 'HIGH')),
    deal_score SMALLINT CHECK (deal_score BETWEEN 0 AND 100),
    classification TEXT CHECK (
        classification IN ('UNAVAILABLE', 'NORMAL', 'REASONABLE', 'INTERESTING', 'GREAT', 'EXCEPTIONAL')
    ),
    provisional BOOLEAN,
    error_code TEXT,
    error_message TEXT,
    UNIQUE (run_id, market_key, period_key),
    CHECK (
        (
            status = 'SUCCESS'
            AND departure_date IS NOT NULL
            AND return_date IS NOT NULL
            AND return_date > departure_date
            AND arrival_airport IS NOT NULL
            AND calendar_price IS NOT NULL
            AND best_price IS NOT NULL
            AND result_count > 0
            AND itinerary_hash IS NOT NULL
            AND legs IS NOT NULL
            AND jsonb_typeof(legs) = 'array'
        )
        OR (
            status <> 'SUCCESS'
            AND departure_date IS NULL
            AND return_date IS NULL
            AND arrival_airport IS NULL
            AND calendar_price IS NULL
            AND best_price IS NULL
            AND result_count = 0
            AND itinerary_hash IS NULL
            AND legs IS NULL
        )
    )
);

CREATE INDEX flexible_market_history_idx
    ON flexible_market_checks (market_key, period_key, checked_at DESC)
    WHERE status = 'SUCCESS' AND best_price IS NOT NULL;

CREATE TABLE flexible_market_alert_history (
    id UUID PRIMARY KEY,
    check_id UUID NOT NULL UNIQUE REFERENCES flexible_market_checks(id) ON DELETE CASCADE,
    market_key TEXT NOT NULL,
    period_key TEXT NOT NULL,
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

CREATE INDEX flexible_market_alert_route_idx
    ON flexible_market_alert_history (market_key, period_key, created_at DESC);

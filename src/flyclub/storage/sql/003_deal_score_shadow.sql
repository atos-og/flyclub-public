CREATE TABLE deal_score_shadow (
    route_check_id UUID NOT NULL REFERENCES route_checks(id) ON DELETE CASCADE,
    route_id UUID NOT NULL REFERENCES monitored_routes(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    sample_size INTEGER NOT NULL CHECK (sample_size >= 0),
    confidence TEXT NOT NULL CHECK (
        confidence IN ('INSUFFICIENT', 'LOW', 'MODERATE', 'HIGH')
    ),
    score SMALLINT CHECK (score BETWEEN 0 AND 100),
    classification TEXT NOT NULL CHECK (
        classification IN ('UNAVAILABLE', 'NORMAL', 'REASONABLE', 'INTERESTING', 'GREAT', 'EXCEPTIONAL')
    ),
    provisional BOOLEAN NOT NULL,
    metrics JSONB NOT NULL,
    PRIMARY KEY (route_check_id, version)
);

CREATE INDEX deal_score_shadow_route_evaluated_idx
    ON deal_score_shadow (route_id, version, evaluated_at DESC);

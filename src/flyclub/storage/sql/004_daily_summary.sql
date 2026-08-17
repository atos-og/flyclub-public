CREATE TABLE daily_summary_history (
    id UUID PRIMARY KEY,
    summary_date DATE NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    delivery_status TEXT NOT NULL CHECK (delivery_status IN ('PENDING', 'SENT', 'FAILED')),
    telegram_message_id TEXT,
    sent_at TIMESTAMPTZ,
    error_code TEXT,
    CHECK (
        (delivery_status = 'PENDING' AND telegram_message_id IS NULL AND sent_at IS NULL)
        OR (delivery_status = 'SENT' AND telegram_message_id IS NOT NULL AND sent_at IS NOT NULL)
        OR (delivery_status = 'FAILED' AND telegram_message_id IS NULL AND sent_at IS NULL)
    )
);

CREATE INDEX daily_summary_history_created_at_idx
    ON daily_summary_history (created_at DESC);

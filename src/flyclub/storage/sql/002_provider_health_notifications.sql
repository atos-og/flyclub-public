ALTER TABLE provider_health
    ADD COLUMN problem_alert_sent_at TIMESTAMPTZ,
    ADD COLUMN recovery_alert_sent_at TIMESTAMPTZ;

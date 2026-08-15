"""Provider-health state shared by monitoring, persistence, and notifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ProviderHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    PROVIDER_CHANGED = "PROVIDER_CHANGED"


class HealthNotificationKind(StrEnum):
    PROBLEM = "PROBLEM"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True, slots=True)
class ProviderHealthState:
    provider: str
    status: ProviderHealthStatus
    last_success_at: datetime | None
    consecutive_problem_runs: int
    incident_started_at: datetime | None
    problem_alert_sent_at: datetime | None
    recovery_alert_sent_at: datetime | None

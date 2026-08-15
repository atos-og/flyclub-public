from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flyclub.alerts.health import ProviderHealthCoordinator
from flyclub.alerts.telegram import TelegramDelivery, TelegramError
from flyclub.health import HealthNotificationKind, ProviderHealthState, ProviderHealthStatus

NOW = datetime(2027, 1, 4, tzinfo=UTC)
LAST_SUCCESS = datetime(2027, 1, 1, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.marked: list[dict[str, object]] = []

    def mark_provider_health_notification(self, **kwargs: object) -> None:
        self.marked.append(kwargs)


class FakeTelegram:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[str] = []

    def send_message(self, text: str) -> TelegramDelivery:
        self.messages.append(text)
        if self.fail:
            raise TelegramError("sanitized failure")
        return TelegramDelivery(message_id="123")


def _state(
    *,
    status: ProviderHealthStatus,
    consecutive: int,
    problem_sent_at: datetime | None = None,
    recovery_sent_at: datetime | None = None,
) -> ProviderHealthState:
    return ProviderHealthState(
        provider="google_flights",
        status=status,
        last_success_at=LAST_SUCCESS,
        consecutive_problem_runs=consecutive,
        incident_started_at=NOW if status is not ProviderHealthStatus.HEALTHY else None,
        problem_alert_sent_at=problem_sent_at,
        recovery_alert_sent_at=recovery_sent_at,
    )


def test_problem_alert_waits_for_configured_consecutive_runs() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = ProviderHealthCoordinator(  # type: ignore[arg-type]
        repository,
        telegram,
        problem_alert_after_runs=3,
    )

    result = coordinator.handle(_state(status=ProviderHealthStatus.DEGRADED, consecutive=2))

    assert result.delivered is False
    assert telegram.messages == []
    assert repository.marked == []


def test_problem_alert_is_sent_and_marked_once_threshold_is_reached() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = ProviderHealthCoordinator(  # type: ignore[arg-type]
        repository,
        telegram,
        problem_alert_after_runs=3,
    )

    result = coordinator.handle(_state(status=ProviderHealthStatus.UNAVAILABLE, consecutive=3))

    assert result.kind is HealthNotificationKind.PROBLEM
    assert result.delivered is True
    assert "últimas 3 execuções" in telegram.messages[0]
    assert "Último sucesso: 01/01/2027 00:00 UTC" in telegram.messages[0]
    assert repository.marked[0]["kind"] is HealthNotificationKind.PROBLEM


def test_existing_problem_notification_is_not_repeated() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = ProviderHealthCoordinator(repository, telegram)  # type: ignore[arg-type]

    result = coordinator.handle(
        _state(
            status=ProviderHealthStatus.PROVIDER_CHANGED,
            consecutive=5,
            problem_sent_at=NOW,
        )
    )

    assert result.delivered is False
    assert telegram.messages == []


def test_recovery_is_sent_only_after_a_reported_incident() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = ProviderHealthCoordinator(repository, telegram)  # type: ignore[arg-type]

    result = coordinator.handle(
        _state(
            status=ProviderHealthStatus.HEALTHY,
            consecutive=0,
            problem_sent_at=LAST_SUCCESS,
        )
    )

    assert result.kind is HealthNotificationKind.RECOVERY
    assert result.delivered is True
    assert "voltou a responder normalmente" in telegram.messages[0]
    assert repository.marked[0]["kind"] is HealthNotificationKind.RECOVERY


def test_recovery_without_prior_warning_needs_no_message() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram()
    coordinator = ProviderHealthCoordinator(repository, telegram)  # type: ignore[arg-type]

    result = coordinator.handle(_state(status=ProviderHealthStatus.HEALTHY, consecutive=0))

    assert result.delivered is False
    assert telegram.messages == []


def test_telegram_failure_leaves_health_notification_pending() -> None:
    repository = FakeRepository()
    telegram = FakeTelegram(fail=True)
    coordinator = ProviderHealthCoordinator(repository, telegram)  # type: ignore[arg-type]

    with pytest.raises(TelegramError, match="sanitized"):
        coordinator.handle(_state(status=ProviderHealthStatus.UNAVAILABLE, consecutive=3))

    assert repository.marked == []


def test_health_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ProviderHealthCoordinator(  # type: ignore[arg-type]
            FakeRepository(),
            FakeTelegram(),
            problem_alert_after_runs=0,
        )

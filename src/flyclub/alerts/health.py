"""Deduplicated Telegram notifications for provider incidents and recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from flyclub.alerts.telegram import TelegramClient
from flyclub.health import HealthNotificationKind, ProviderHealthState, ProviderHealthStatus


class ProviderHealthRepository(Protocol):
    def mark_provider_health_notification(
        self,
        *,
        provider: str,
        kind: HealthNotificationKind,
        sent_at: datetime | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class HealthNotificationResult:
    kind: HealthNotificationKind | None
    delivered: bool


def _provider_label(provider: str) -> str:
    return provider.replace("_", " ").title()


def _problem_message(state: ProviderHealthState) -> str:
    last_success = (
        "ainda não registrado"
        if state.last_success_at is None
        else state.last_success_at.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")
    )
    return (
        "⚠️ Fly Club com problema\n\n"
        f"{_provider_label(state.provider)} apresentou problemas nas últimas "
        f"{state.consecutive_problem_runs} execuções.\n"
        f"Status: {state.status.value}.\n"
        f"Último sucesso: {last_success}."
    )


def _recovery_message(state: ProviderHealthState) -> str:
    return (
        "✅ Fly Club recuperado\n\n"
        f"{_provider_label(state.provider)} voltou a responder normalmente."
    )


class ProviderHealthCoordinator:
    def __init__(
        self,
        repository: ProviderHealthRepository,
        telegram: TelegramClient,
        *,
        problem_alert_after_runs: int = 3,
    ) -> None:
        if problem_alert_after_runs < 1:
            raise ValueError("problem_alert_after_runs must be at least 1")
        self._repository = repository
        self._telegram = telegram
        self._problem_alert_after_runs = problem_alert_after_runs

    def handle(self, state: ProviderHealthState) -> HealthNotificationResult:
        kind = self._notification_due(state)
        if kind is None:
            return HealthNotificationResult(kind=None, delivered=False)

        message = (
            _problem_message(state)
            if kind is HealthNotificationKind.PROBLEM
            else _recovery_message(state)
        )
        self._telegram.send_message(message)
        self._repository.mark_provider_health_notification(
            provider=state.provider,
            kind=kind,
            sent_at=datetime.now(UTC),
        )
        return HealthNotificationResult(kind=kind, delivered=True)

    def _notification_due(self, state: ProviderHealthState) -> HealthNotificationKind | None:
        if (
            state.status is not ProviderHealthStatus.HEALTHY
            and state.consecutive_problem_runs >= self._problem_alert_after_runs
            and state.problem_alert_sent_at is None
        ):
            return HealthNotificationKind.PROBLEM
        if (
            state.status is ProviderHealthStatus.HEALTHY
            and state.problem_alert_sent_at is not None
            and state.recovery_alert_sent_at is None
        ):
            return HealthNotificationKind.RECOVERY
        return None

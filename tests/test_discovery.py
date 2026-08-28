from pathlib import Path

import pytest

from flyclub.alerts.telegram import TelegramError
from flyclub.config import ConfigError
from flyclub.discovery import cli
from flyclub.storage.postgres import StorageError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / "examples" / "github-actions" / "discovery.example.yml"


def test_discovery_workflow_runs_three_times_per_week_after_cost_approval() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert 'cron: "23 9 * * 1,3,6"' in text
    assert "flyclub-discovery" in text
    assert "HEALTHCHECKS_PING_URL" not in text
    assert "FLYCLUB_CONFIRMATION_WORKFLOW_URL: ${{ github.server_url }}/" in text


def test_discovery_cli_uses_independent_routes_without_provider_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr("flyclub.discovery.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.discovery.load_config", lambda _path: object())
    monkeypatch.setattr("flyclub.discovery.plan_discovery_routes", lambda _config: ("route",))
    monkeypatch.setattr(
        "flyclub.discovery._run_all_routes",
        lambda config, routes, **kwargs: (
            captured.append({"config": config, "routes": routes, **kwargs}) or 0
        ),
    )

    assert cli(["--dry-run"]) == 0
    assert captured[0]["routes"] == ("route",)
    assert captured[0]["dry_run"] is True
    assert captured[0]["include_health"] is False


def test_discovery_cli_rejects_configuration_without_routes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("flyclub.discovery.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.discovery.load_config", lambda _path: object())
    monkeypatch.setattr("flyclub.discovery.plan_discovery_routes", lambda _config: ())

    assert cli([]) == 2
    assert "no discovery routes" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigError("invalid example"), "Configuration error"),
        (StorageError("unavailable"), "Storage error"),
        (TelegramError("unavailable"), "Notification error"),
    ],
)
def test_discovery_cli_reports_sanitized_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr("flyclub.discovery.load_dotenv", lambda *, override: None)
    if isinstance(error, ConfigError):
        monkeypatch.setattr(
            "flyclub.discovery.load_config", lambda _path: (_ for _ in ()).throw(error)
        )
    else:
        monkeypatch.setattr("flyclub.discovery.load_config", lambda _path: object())
        monkeypatch.setattr("flyclub.discovery.plan_discovery_routes", lambda _config: ("route",))
        monkeypatch.setattr(
            "flyclub.discovery._run_all_routes",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
        )

    assert cli([]) == 1
    assert expected in capsys.readouterr().err

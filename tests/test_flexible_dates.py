from pathlib import Path

import pytest

from flyclub.flexible_dates import cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "flexible-dates.yml"


def test_flexible_workflow_uses_two_daily_sequential_shards() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "33 7 * * *"' in text
    assert 'cron: "33 19 * * *"' in text
    assert "workflow_dispatch:" in text
    assert 'offsets="-3,-2,-1"' in text
    assert 'offsets="1,2,3"' in text
    assert 'flyclub-flexible-dates --offsets="${offsets}"' in text
    assert "timeout-minutes: 25" in text
    assert "flyclub-monitor" not in text
    assert "HEALTHCHECKS_PING_URL" not in text


def test_flexible_cli_uses_dedicated_routes_without_provider_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr("flyclub.flexible_dates.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.flexible_dates.load_config", lambda _path: object())
    monkeypatch.setattr(
        "flyclub.flexible_dates.plan_flexible_date_routes",
        lambda _config, *, offsets: ("flex", offsets),
    )
    monkeypatch.setattr(
        "flyclub.flexible_dates._run_all_routes",
        lambda config, routes, **kwargs: (
            captured.append({"config": config, "routes": routes, **kwargs}) or 0
        ),
    )

    assert cli(["--dry-run", "--offsets=-3,-2,-1"]) == 0
    assert captured[0]["routes"] == ("flex", (-3, -2, -1))
    assert captured[0]["dry_run"] is True
    assert captured[0]["include_health"] is False


def test_flexible_cli_rejects_zero_offset() -> None:
    with pytest.raises(SystemExit):
        cli(["--dry-run", "--offsets=-1,0,1"])

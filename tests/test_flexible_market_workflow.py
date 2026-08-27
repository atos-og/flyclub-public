from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / "examples" / "github-actions" / "flexible-market.example.yml"
ACTIVE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "flexible-market.yml"


def test_flexible_market_workflow_is_isolated_and_runs_twice_daily() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "35 11,23 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "flyclub-flexible-market" in text
    assert "FLYCLUB_FLEXIBLE_MARKETS_YAML" in text
    assert "FLYCLUB_ROUTES_YAML" not in text
    assert "HEALTHCHECKS_PING_URL" not in text
    assert "timeout-minutes: 15" in text


def test_flexible_market_workflow_is_inert_in_public_source() -> None:
    assert not ACTIVE_WORKFLOW.exists()


def test_real_flexible_market_configuration_is_ignored() -> None:
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "config/flexible-markets.yaml" in text
    assert "config/flexible-markets.local.yaml" in text

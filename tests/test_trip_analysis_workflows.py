from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATE_WORKFLOW = PROJECT_ROOT / "examples" / "github-actions" / "compare-dates.example.yml"
RISK_WORKFLOW = PROJECT_ROOT / "examples" / "github-actions" / "compare-fare-risk.example.yml"


def test_date_workflow_is_manual_bounded_and_non_persistent() -> None:
    text = DATE_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    for name in (
        "origin",
        "destination",
        "departure_date",
        "return_date",
        "window_days",
        "passengers",
        "max_stops",
    ):
        assert f"      {name}:" in text
    assert '          - "3"' in text
    assert "flyclub-date-matrix" in text
    assert "timeout-minutes: 25" in text
    assert "DATABASE_URL" not in text
    assert "FLYCLUB_ROUTES_YAML" not in text
    assert "schedule:" not in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in text
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in text


def test_risk_workflow_requires_explicit_rules_sources_and_has_no_provider_or_database() -> None:
    text = RISK_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    for option in ("a", "b"):
        for field in (
            "label",
            "price",
            "cancellation",
            "cancellation_penalty",
            "change",
            "change_penalty",
            "fare_difference",
            "source_url",
            "verified_on",
        ):
            assert f"      option_{option}_{field}:" in text
    assert "flyclub-fare-risk" in text
    assert "DATABASE_URL" not in text
    assert "FLYCLUB_ROUTES_YAML" not in text
    assert "flyclub-date-matrix" not in text
    assert "schedule:" not in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in text
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in text

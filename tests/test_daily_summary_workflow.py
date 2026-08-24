from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / "examples" / "github-actions" / "daily-summary.example.yml"


def test_daily_summary_runs_once_each_brasilia_morning_and_manually() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "23 11 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "flyclub-daily-summary" in text


def test_daily_summary_reads_persisted_prices_without_provider_search() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "flyclub-db-migrate" in text
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in text
    assert "FLYCLUB_ROUTES_YAML: ${{ secrets.FLYCLUB_ROUTES_YAML }}" in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in text
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in text
    assert "flyclub --monitor" not in text
    assert "flyclub-discovery" not in text
    assert "flyclub-flexible-dates" not in text

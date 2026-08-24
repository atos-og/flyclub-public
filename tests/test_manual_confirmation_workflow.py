from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (
    PROJECT_ROOT / "examples" / "github-actions" / "confirm-two-passengers.example.yml"
)


def test_manual_confirmation_workflow_has_required_inputs_and_no_persistence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    for name in ("origin", "destination", "departure_date", "return_date"):
        assert f"      {name}:" in text
    assert "flyclub-confirm-two" in text
    assert "DATABASE_URL" not in text
    assert "FLYCLUB_ROUTES_YAML" not in text
    assert "flyclub-db-migrate" not in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in text
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in text

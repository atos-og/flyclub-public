from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / "examples" / "github-actions" / "monitor.example.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_native_schedule_is_a_thirty_minute_delayed_fallback() -> None:
    workflow = _workflow_text()

    assert 'cron: "47 0,3,6,9,12,15,18,21 * * *"' in workflow
    assert 'cron: "17 2,5,8,11,14,17,20,23 * * *"' in workflow
    assert 'cron: "17 */3 * * *"' not in workflow


def test_manual_dispatch_and_duplicate_safe_fallback_coexist() -> None:
    workflow = _workflow_text()

    assert "workflow_dispatch:" in workflow
    assert "actions: read" in workflow
    assert "event=workflow_dispatch&per_page=10" in workflow
    assert "date -u -d '70 minutes ago'" in workflow
    assert "native fallback will run" in workflow
    assert workflow.count("steps.schedule_guard.outputs.should_run == 'true'") == 8


def test_healthchecks_wraps_the_main_monitor_flow() -> None:
    workflow = _workflow_text()

    start = workflow.index("- name: Notify Healthchecks start")
    checkout = workflow.index("- name: Check out repository")
    monitor = workflow.index("- name: Run monitor")
    completion = workflow.index("- name: Notify Healthchecks completion")

    assert start < checkout < monitor < completion
    assert '"${HEALTHCHECKS_PING_URL}/start"' in workflow
    assert '"${HEALTHCHECKS_PING_URL}"' in workflow
    assert '"${HEALTHCHECKS_PING_URL}/fail"' in workflow
    assert "if: ${{ always() && steps.schedule_guard.outputs.should_run == 'true' }}" in workflow
    assert "MONITOR_JOB_STATUS: ${{ job.status }}" in workflow


def test_healthchecks_pings_are_bounded_and_best_effort() -> None:
    workflow = _workflow_text()

    assert workflow.count("--max-time 10 --retry 5") == 2
    assert "Healthchecks start ping failed; monitor will continue" in workflow
    assert "Healthchecks ${ping_state} ping failed; job result is unchanged" in workflow


def test_healthchecks_url_is_read_only_from_a_repository_secret() -> None:
    workflow = _workflow_text()

    secret_reference = "HEALTHCHECKS_PING_URL: ${{ secrets.HEALTHCHECKS_PING_URL }}"
    assert workflow.count(secret_reference) == 3
    assert "HEALTHCHECKS_PING_URL; do" in workflow
    assert "hc-ping.com" not in workflow
    assert "healthchecks.io/api" not in workflow


def test_confirmation_workflow_url_comes_from_the_current_private_repository() -> None:
    workflow = _workflow_text()

    assert (
        "FLYCLUB_CONFIRMATION_WORKFLOW_URL: ${{ github.server_url }}/"
        "${{ github.repository }}/actions/workflows/confirm-two-passengers.yml"
    ) in workflow
    assert "secrets.FLYCLUB_CONFIRMATION_WORKFLOW_URL" not in workflow

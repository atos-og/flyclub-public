from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "monitor.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


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
    assert "if: ${{ always() }}" in workflow
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

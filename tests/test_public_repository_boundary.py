from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
DEPLOYMENT_TEMPLATES = PROJECT_ROOT / "examples" / "github-actions"


def test_public_repository_activates_only_ci() -> None:
    active = {path.name for path in ACTIVE_WORKFLOWS.glob("*.yml")}

    assert active == {"ci.yml"}
    assert "schedule:" not in (ACTIVE_WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_private_deployment_workflows_are_inert_pinned_source_templates() -> None:
    templates = tuple(sorted(DEPLOYMENT_TEMPLATES.glob("*.example.yml")))

    assert len(templates) == 7
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert yaml.safe_load(text) is not None
        assert "repository: ${{ vars.FLYCLUB_SOURCE_REPOSITORY }}" in text
        assert "ref: ${{ vars.FLYCLUB_SOURCE_REF }}" in text
        assert "persist-credentials: false" in text


def test_public_environment_example_contains_names_without_values() -> None:
    lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assignments = [line for line in lines if line and not line.startswith("#")]

    assert assignments
    assert all(line.endswith("=") for line in assignments)


def test_package_does_not_hardcode_the_owners_private_workflow_url() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "flyclub").rglob("*.py")
    )

    assert "atos-og/flyclub/actions/workflows" not in source

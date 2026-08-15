from pathlib import Path

import pytest

from flyclub.config import ConfigError, load_config, load_config_text
from flyclub.models import OriginRole

EXAMPLE_PATH = Path("config/routes.example.yaml")


def test_public_example_is_valid() -> None:
    config = load_config(EXAMPLE_PATH)

    assert config.trip.currency == "BRL"
    assert config.origins["from_bh"].airports == ("CNF",)
    assert config.origins["from_sao_paulo"].role is OriginRole.POSITIONING
    assert len(config.destinations) == 3
    assert config.analysis.deal_score_weights.percentile == 40
    assert sum(config.analysis.deal_score_weights.model_dump().values()) == 100
    assert config.health.problem_alert_after_runs == 3
    assert config.alerts.positioning_context_min_savings == 100
    assert config.origins["from_sao_paulo"].positioning_cost_estimate == 650


def test_environment_yaml_takes_precedence_over_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLYCLUB_ROUTES_YAML", EXAMPLE_PATH.read_text(encoding="utf-8"))

    config = load_config("missing-private-file.yaml")

    assert config.destinations[0].code == "LIS"


def test_positioning_origin_requires_a_notice() -> None:
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace(
        '    notice: "Saída de São Paulo — deslocamento BH → SP não incluído."\n', ""
    )

    with pytest.raises(ConfigError, match="POSITIONING origin requires a notice"):
        load_config_text(content)


def test_positioning_origin_requires_a_cost_estimate() -> None:
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace(
        "    positioning_cost_estimate: 650\n", ""
    )

    with pytest.raises(ConfigError, match="requires a positioning cost estimate"):
        load_config_text(content)


def test_validation_error_does_not_echo_input_value() -> None:
    private_value = "PRIVATE_DESTINATION_SENTINEL"
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace("LIS", private_value, 1)

    with pytest.raises(ConfigError) as captured:
        load_config_text(content)

    assert private_value not in str(captured.value)


def test_duplicate_destination_is_rejected() -> None:
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace("  - code: MAD", "  - code: LIS")

    with pytest.raises(ConfigError, match="duplicate IATA codes"):
        load_config_text(content)


def test_deal_score_weights_must_total_one_hundred() -> None:
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace(
        "    percentile: 40", "    percentile: 39"
    )

    with pytest.raises(ConfigError, match="weights must total 100"):
        load_config_text(content)


def test_deployment_schedule_is_not_accepted_as_route_configuration() -> None:
    content = EXAMPLE_PATH.read_text(encoding="utf-8").replace(
        "monitor:\n", "monitor:\n  interval_hours: 3\n"
    )

    with pytest.raises(ConfigError, match="Extra inputs are not permitted"):
        load_config_text(content)

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

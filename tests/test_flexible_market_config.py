from __future__ import annotations

from decimal import Decimal

import pytest

from flyclub.flexible_market_config import (
    FlexibleMarketConfigError,
    flexible_market_fingerprint,
    load_flexible_market_config,
    load_flexible_market_text,
)


def _yaml() -> str:
    return """
markets:
  - id: sample_market
    label: Sample market
    origin_airports: [jfk]
    destination_airports: [lhr, lgw]
    trip_duration_days: 10
    passengers: 1
    cabin: ECONOMY
    currency: usd
    max_stops: ANY
    minimum_days_ahead: 14
    maximum_days_ahead: 305
    score_threshold_2026: 80
    score_threshold_future: 75
retry_base_delay_seconds: 2
"""


def test_loads_strict_private_flexible_market_configuration() -> None:
    settings = load_flexible_market_text(_yaml())
    market = settings.markets[0]

    assert market.origin_airports == ("JFK",)
    assert market.destination_airports == ("LHR", "LGW")
    assert market.trip_duration_days == 10
    assert market.score_threshold_2026 == 80
    assert market.score_threshold_future == 75
    assert settings.retry_base_delay_seconds == Decimal("2")


def test_fixed_travel_window_requires_and_contains_a_complete_trip() -> None:
    configured = load_flexible_market_text(
        _yaml().replace(
            "    score_threshold_future: 75",
            "    score_threshold_future: 75\n"
            "    travel_window_start: 2027-01-01\n"
            "    travel_window_end: 2027-01-31",
        )
    )

    assert configured.markets[0].travel_window_start.isoformat() == "2027-01-01"
    assert configured.markets[0].travel_window_end.isoformat() == "2027-01-31"

    for invalid in (
        _yaml().replace(
            "    score_threshold_future: 75",
            "    score_threshold_future: 75\n    travel_window_start: 2027-01-01",
        ),
        _yaml().replace(
            "    score_threshold_future: 75",
            "    score_threshold_future: 75\n"
            "    travel_window_start: 2027-01-31\n"
            "    travel_window_end: 2027-02-05",
        ),
    ):
        with pytest.raises(FlexibleMarketConfigError):
            load_flexible_market_text(invalid)


def test_private_configuration_errors_do_not_echo_values() -> None:
    private_value = "private-market-name"

    with pytest.raises(FlexibleMarketConfigError) as captured:
        load_flexible_market_text(
            _yaml().replace("sample_market", private_value).replace("JFK", "INVALID")
        )

    assert private_value not in str(captured.value)
    assert "INVALID" not in str(captured.value)


def test_fingerprint_is_stable_and_sensitive_without_exposing_configuration() -> None:
    first = load_flexible_market_text(_yaml())
    changed = load_flexible_market_text(
        _yaml().replace("trip_duration_days: 10", "trip_duration_days: 9")
    )

    assert flexible_market_fingerprint(first) == flexible_market_fingerprint(first)
    assert flexible_market_fingerprint(first) != flexible_market_fingerprint(changed)


def test_environment_configuration_precedes_local_file(monkeypatch) -> None:
    monkeypatch.setenv("FLYCLUB_FLEXIBLE_MARKETS_YAML", _yaml())

    settings = load_flexible_market_config("missing-private.yaml")

    assert settings.markets[0].id == "sample_market"


def test_explicit_local_file_is_supported_without_logging_values(monkeypatch) -> None:
    monkeypatch.delenv("FLYCLUB_FLEXIBLE_MARKETS_YAML", raising=False)
    monkeypatch.setattr("pathlib.Path.read_text", lambda _path, *, encoding: _yaml())

    assert load_flexible_market_config("private.yaml").markets[0].trip_duration_days == 10


@pytest.mark.parametrize(
    "replacement",
    [
        ("id: sample_market", "id: INVALID-ID"),
        ("origin_airports: [jfk]", "origin_airports: [JFK, JFK]"),
        ("currency: usd", "currency: INVALID"),
        ("minimum_days_ahead: 14", "minimum_days_ahead: 305"),
    ],
)
def test_rejects_incomparable_or_ambiguous_market_configuration(replacement) -> None:
    before, after = replacement

    with pytest.raises(FlexibleMarketConfigError):
        load_flexible_market_text(_yaml().replace(before, after))

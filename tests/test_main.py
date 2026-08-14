from decimal import Decimal

import pytest

from flyclub.main import cli
from flyclub.models import FlightOption, SearchOutcome, SearchStatus


class FakeGoogleFlightsProvider:
    outcome = SearchOutcome(
        provider="google_flights",
        status=SearchStatus.SUCCESS,
        options=(
            FlightOption(
                price=Decimal("3030"),
                currency="BRL",
                legs=(),
                stops=1,
                google_flights_url="https://www.google.com/travel/flights/booking?tfs=test",
            ),
        ),
    )

    def __init__(self, **_: object) -> None:
        pass

    def search(self, *_: object, **__: object) -> SearchOutcome:
        return self.outcome


def test_cli_runs_one_explicit_search_without_real_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "flyclub.providers.google_flights.GoogleFlightsProvider", FakeGoogleFlightsProvider
    )

    exit_code = cli(
        [
            "--config",
            "config/routes.example.yaml",
            "--search-route",
            "from_bh:LIS",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Provider status: SUCCESS" in output
    assert "BRL 3030" in output
    assert "https://www.google.com/travel/flights/booking?tfs=test" in output


def test_cli_rejects_unknown_route_without_searching(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "flyclub.providers.google_flights.GoogleFlightsProvider", FakeGoogleFlightsProvider
    )

    exit_code = cli(
        [
            "--config",
            "config/routes.example.yaml",
            "--search-route",
            "from_bh:XXX",
        ]
    )

    error = capsys.readouterr().err
    assert exit_code == 2
    assert "does not match exactly one configured route" in error

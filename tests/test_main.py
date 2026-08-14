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


def test_cli_requires_monitor_for_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli(["--config", "config/routes.example.yaml", "--dry-run"])

    assert exit_code == 2
    assert "--dry-run requires --monitor" in capsys.readouterr().err


def test_cli_runs_full_monitor_in_safe_dry_run_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "flyclub.providers.google_flights.GoogleFlightsProvider", FakeGoogleFlightsProvider
    )

    exit_code = cli(["--config", "config/routes.example.yaml", "--monitor", "--dry-run"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SUCCESS (dry-run)" in output
    assert "Planned routes: 6" in output
    assert "Successful routes: 6" in output
    assert "LIS" not in output
    assert "https://" not in output


def test_cli_monitor_without_database_fails_safely(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    exit_code = cli(["--config", "config/routes.example.yaml", "--monitor"])

    assert exit_code == 1
    assert "DATABASE_URL is not configured" in capsys.readouterr().err

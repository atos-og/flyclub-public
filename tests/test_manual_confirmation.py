from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import pytest

from flyclub.manual_confirmation import cli
from flyclub.models import FlightOption, SearchOutcome, SearchStatus


class FakeProvider:
    routes: ClassVar[list[object]] = []

    def __init__(self, **_: object) -> None:
        pass

    def search(self, route: object, *, max_results: int) -> SearchOutcome:
        self.routes.append(route)
        assert max_results == 5
        return SearchOutcome(
            provider="google_flights",
            status=SearchStatus.SUCCESS,
            options=(FlightOption(price=Decimal("4000"), currency="BRL", legs=()),),
        )


class FakeTelegram:
    messages: ClassVar[list[str]] = []

    @classmethod
    def from_env(cls) -> FakeTelegram:
        return cls()

    def send_message(self, message: str) -> None:
        self.messages.append(message)


def test_manual_confirmation_queries_two_passengers_and_sends_without_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeProvider.routes = []
    FakeTelegram.messages = []
    monkeypatch.setattr("flyclub.manual_confirmation.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.manual_confirmation.GoogleFlightsProvider", FakeProvider)
    monkeypatch.setattr("flyclub.manual_confirmation.TelegramClient", FakeTelegram)

    result = cli(
        [
            "--origin",
            "cnf",
            "--destination",
            "scl",
            "--departure-date",
            "2030-03-10",
            "--return-date",
            "2030-03-17",
        ]
    )

    route = FakeProvider.routes[0]
    assert result == 0
    assert route.passengers == 2
    assert route.origin_airports == ("CNF",)
    assert route.destination == "SCL"
    assert FakeTelegram.messages[0].startswith("👥 CONFIRMAÇÃO MANUAL")
    assert "no history was persisted" in capsys.readouterr().out


def test_manual_confirmation_rejects_invalid_date_order_before_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeProvider.routes = []
    monkeypatch.setattr("flyclub.manual_confirmation.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.manual_confirmation.GoogleFlightsProvider", FakeProvider)

    result = cli(
        [
            "--origin",
            "CNF",
            "--destination",
            "SCL",
            "--departure-date",
            "2030-03-17",
            "--return-date",
            "2030-03-10",
        ]
    )

    assert result == 2
    assert FakeProvider.routes == []
    assert "return date must be after departure date" in capsys.readouterr().err

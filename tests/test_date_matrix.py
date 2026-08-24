from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import ClassVar

import pytest

from flyclub.alerts.telegram import TelegramError
from flyclub.date_matrix import (
    DateCandidate,
    DateMatrixResult,
    build_base_route,
    cli,
    date_matrix_routes,
    format_date_matrix_message,
    rank_date_candidates,
    scan_date_matrix,
)
from flyclub.models import FlightOption, MaxStops, SearchOutcome, SearchStatus


def _route():
    return build_base_route(
        origin="BOS",
        destination="YUL",
        departure_date=date(2030, 7, 10),
        return_date=date(2030, 7, 17),
        passengers=1,
        max_stops=MaxStops.ANY,
    )


def _candidate(
    departure_shift: int,
    return_shift: int,
    price: str,
    *,
    stops: int | None = 1,
    duration: int | None = 600,
    url: str | None = None,
) -> DateCandidate:
    base = _route()
    planned = next(
        route
        for route, departure, returning in date_matrix_routes(base, window_days=3)
        if departure == departure_shift and returning == return_shift
    )
    return DateCandidate(
        route=planned,
        option=FlightOption(
            price=Decimal(price),
            currency="BRL",
            legs=(),
            stops=stops,
            duration_minutes=duration,
            google_flights_url=url,
        ),
        departure_shift_days=departure_shift,
        return_shift_days=return_shift,
    )


def test_date_matrix_varies_departure_and_return_independently() -> None:
    planned = date_matrix_routes(_route(), window_days=3)

    assert len(planned) == 49
    shifts = {(departure, returning) for _, departure, returning in planned}
    assert (-3, 3) in shifts
    assert (3, -3) in shifts
    assert (0, 0) in shifts
    assert len({route.key for route, _, _ in planned}) == 49


def test_date_matrix_rejects_unbounded_windows() -> None:
    for window in (0, 4):
        with pytest.raises(ValueError, match="between 1 and 3"):
            date_matrix_routes(_route(), window_days=window)


def test_ranking_uses_price_then_itinerary_and_smallest_date_change() -> None:
    candidates = (
        _candidate(-2, 2, "900", stops=0, duration=500),
        _candidate(-1, 0, "900", stops=0, duration=500),
        _candidate(0, 0, "1000", stops=0, duration=400),
        _candidate(1, 1, "900", stops=1, duration=300),
    )

    ranked = rank_date_candidates(candidates)

    assert [(item.departure_shift_days, item.return_shift_days) for item in ranked] == [
        (-1, 0),
        (-2, 2),
        (1, 1),
        (0, 0),
    ]


class SequencedProvider:
    name = "fake"

    def __init__(self, statuses: list[SearchStatus]) -> None:
        self.statuses = iter(statuses)
        self.routes: list[object] = []

    def search(self, route: object, *, max_results: int) -> SearchOutcome:
        self.routes.append(route)
        assert max_results == 1
        status = next(self.statuses)
        if status is SearchStatus.SUCCESS:
            return SearchOutcome(
                provider=self.name,
                status=status,
                options=(FlightOption(price=Decimal("1000"), currency="BRL", legs=()),),
            )
        return SearchOutcome(provider=self.name, status=status)


def test_scan_accounts_for_success_empty_and_failure_sequentially() -> None:
    statuses = [SearchStatus.SUCCESS, SearchStatus.EMPTY, SearchStatus.TEMPORARY_FAILURE] * 3
    provider = SequencedProvider(statuses)

    result = scan_date_matrix(provider, _route(), window_days=1)

    assert result.attempted == 9
    assert len(result.candidates) == 3
    assert result.empty == 3
    assert result.failed == 3
    assert len(provider.routes) == 9


def test_formatter_explains_savings_and_keeps_analysis_isolated() -> None:
    result = DateMatrixResult(
        attempted=49,
        candidates=(
            _candidate(-1, 1, "800", stops=0, url="https://example.com/cheap"),
            _candidate(1, 0, "900", stops=1),
            _candidate(0, 0, "1000", stops=0),
            _candidate(2, 2, "1100", stops=0),
        ),
        empty=2,
        failed=1,
    )

    message = format_date_matrix_message(base_route=_route(), result=result)

    assert message.startswith("🗓️ COMPARADOR DE DATAS · TOP 3")
    assert "49 combinações consultadas · 4 com preço" in message
    assert "Economiza R$ 200,00 (20,0%) vs. datas desejadas." in message
    assert "ida 1 dia antes · volta 1 dia depois" in message
    assert "https://example.com/cheap" in message
    assert "Não altera histórico, Deal Score ou alertas automáticos." in message
    assert "1100" not in message


class AlwaysSuccessProvider:
    routes: ClassVar[list[object]] = []

    def __init__(self) -> None:
        pass

    def search(self, route: object, *, max_results: int) -> SearchOutcome:
        self.routes.append(route)
        return SearchOutcome(
            provider="fake",
            status=SearchStatus.SUCCESS,
            options=(FlightOption(price=Decimal("1000"), currency="BRL", legs=()),),
        )


class AlwaysEmptyProvider:
    name = "fake"

    def search(self, route: object, *, max_results: int) -> SearchOutcome:
        return SearchOutcome(provider=self.name, status=SearchStatus.EMPTY)


class FakeTelegram:
    messages: ClassVar[list[str]] = []

    @classmethod
    def from_env(cls) -> FakeTelegram:
        return cls()

    def send_message(self, message: str) -> None:
        self.messages.append(message)


class FailingTelegram:
    @classmethod
    def from_env(cls) -> FailingTelegram:
        return cls()

    def send_message(self, message: str) -> None:
        raise TelegramError("simulated failure")


def test_cli_sends_one_manual_comparison_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    AlwaysSuccessProvider.routes = []
    FakeTelegram.messages = []
    monkeypatch.setattr("flyclub.date_matrix.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.date_matrix.GoogleFlightsProvider", AlwaysSuccessProvider)
    monkeypatch.setattr("flyclub.date_matrix.TelegramClient", FakeTelegram)

    result = cli(
        [
            "--origin",
            "bos",
            "--destination",
            "yul",
            "--departure-date",
            "2030-07-10",
            "--return-date",
            "2030-07-17",
            "--window-days",
            "1",
            "--passengers",
            "2",
        ]
    )

    assert result == 0
    assert len(AlwaysSuccessProvider.routes) == 9
    assert len(FakeTelegram.messages) == 1
    assert "2 passageiros" in FakeTelegram.messages[0]
    assert "no history was persisted" in capsys.readouterr().out


def test_cli_rejects_invalid_date_order_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    AlwaysSuccessProvider.routes = []
    monkeypatch.setattr("flyclub.date_matrix.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.date_matrix.GoogleFlightsProvider", AlwaysSuccessProvider)

    result = cli(
        [
            "--origin",
            "BOS",
            "--destination",
            "YUL",
            "--departure-date",
            "2030-07-17",
            "--return-date",
            "2030-07-10",
        ]
    )

    assert result == 2
    assert AlwaysSuccessProvider.routes == []


def test_cli_reports_aggregate_when_no_combination_has_a_price(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("flyclub.date_matrix.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.date_matrix.GoogleFlightsProvider", AlwaysEmptyProvider)

    result = cli(
        [
            "--origin",
            "BOS",
            "--destination",
            "YUL",
            "--departure-date",
            "2030-07-10",
            "--return-date",
            "2030-07-17",
            "--window-days",
            "1",
        ]
    )

    assert result == 1
    assert "empty=9, failed=0" in capsys.readouterr().err


def test_cli_reports_sanitized_telegram_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("flyclub.date_matrix.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.date_matrix.GoogleFlightsProvider", AlwaysSuccessProvider)
    monkeypatch.setattr("flyclub.date_matrix.TelegramClient", FailingTelegram)

    result = cli(
        [
            "--origin",
            "BOS",
            "--destination",
            "YUL",
            "--departure-date",
            "2030-07-10",
            "--return-date",
            "2030-07-17",
            "--window-days",
            "1",
        ]
    )

    assert result == 1
    assert "Notification error: simulated failure" in capsys.readouterr().err

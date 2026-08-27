from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fli.models import Airline, Airport, FlightResult
from fli.models import FlightLeg as FliFlightLeg
from fli.search.flights import SearchParseError

from flyclub.flexible_market_models import FlexibleMarketDefinition
from flyclub.models import CabinClass, MaxStops, SearchStatus
from flyclub.providers.google_flights_flexible import GoogleFlightsFlexibleProvider


def _market() -> FlexibleMarketDefinition:
    return FlexibleMarketDefinition(
        key="sample_market",
        label="Sample market",
        origin_airports=("JFK",),
        destination_airports=("LHR", "LGW"),
        trip_duration_days=10,
        passengers=1,
        cabin=CabinClass.ECONOMY,
        currency="USD",
        max_stops=MaxStops.ANY,
        minimum_days_ahead=14,
        maximum_days_ahead=305,
        score_threshold_2026=80,
        score_threshold_future=75,
    )


class FakeCalendarClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = iter(responses)
        self.calls: list[Any] = []

    def search(self, filters: Any, **_kwargs: Any) -> list[Any] | None:
        self.calls.append(filters)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeFlightClient:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[Any] = []

    def search(self, filters: Any, **_kwargs: Any) -> list[Any] | None:
        self.calls.append(filters)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def build_flight_booking_url(self, _flight: Any, **_kwargs: Any) -> str:
        return "https://www.google.com/travel/flights/booking?tfs=sample"


def _date_fare(departure: str, returning: str, price: float) -> Any:
    return SimpleNamespace(
        date=(datetime.fromisoformat(departure), datetime.fromisoformat(returning)),
        price=price,
        currency="USD",
    )


def _round_trip() -> tuple[FlightResult, FlightResult]:
    outbound_leg = FliFlightLeg(
        airline=Airline.BA,
        flight_number="117",
        departure_airport=Airport.JFK,
        arrival_airport=Airport.LHR,
        departure_datetime=datetime(2027, 1, 10, 12),
        arrival_datetime=datetime(2027, 1, 10, 22),
        duration=600,
    )
    inbound_leg = FliFlightLeg(
        airline=Airline.BA,
        flight_number="118",
        departure_airport=Airport.LHR,
        arrival_airport=Airport.JFK,
        departure_datetime=datetime(2027, 1, 20, 12),
        arrival_datetime=datetime(2027, 1, 20, 22),
        duration=600,
    )
    return (
        FlightResult(legs=[outbound_leg], price=850.25, currency="USD", duration=600, stops=0),
        FlightResult(legs=[inbound_leg], price=850.25, currency="USD", duration=600, stops=0),
    )


def test_calendar_range_is_chunked_sequentially_and_money_becomes_decimal() -> None:
    client = FakeCalendarClient(
        [
            [_date_fare("2027-01-10", "2027-01-20", 900.1)],
            [_date_fare("2027-03-05", "2027-03-15", 850.25)],
        ]
    )
    provider = GoogleFlightsFlexibleProvider(
        calendar_chunk_days=61,
        calendar_client_factory=lambda: client,
    )

    outcome = provider.search_calendar(
        _market(), start_date=date(2027, 1, 1), end_date=date(2027, 4, 1)
    )

    assert outcome.status is SearchStatus.SUCCESS
    assert outcome.request_count == 2
    assert [fare.price for fare in outcome.fares] == [Decimal("850.25"), Decimal("900.1")]
    assert client.calls[0].from_date == "2027-01-01"
    assert client.calls[0].to_date == "2027-03-02"
    assert client.calls[1].from_date == "2027-03-03"
    assert client.calls[1].to_date == "2027-04-01"


def test_one_failed_calendar_chunk_discards_incomplete_window() -> None:
    client = FakeCalendarClient([[_date_fare("2027-01-10", "2027-01-20", 900)], TimeoutError()])
    provider = GoogleFlightsFlexibleProvider(
        retry_attempts=1,
        calendar_chunk_days=61,
        calendar_client_factory=lambda: client,
    )

    outcome = provider.search_calendar(
        _market(), start_date=date(2027, 1, 1), end_date=date(2027, 4, 1)
    )

    assert outcome.status is SearchStatus.TEMPORARY_FAILURE
    assert outcome.fares == ()
    assert outcome.error_code == "TimeoutError"


def test_exact_verification_uses_airport_groups_and_returns_normalized_option() -> None:
    client = FakeFlightClient([_round_trip()])
    provider = GoogleFlightsFlexibleProvider(flight_client_factory=lambda: client)

    outcome = provider.verify(
        _market(),
        departure_date=date(2027, 1, 10),
        return_date=date(2027, 1, 20),
        max_results=5,
    )

    assert outcome.status is SearchStatus.SUCCESS
    assert outcome.options[0].price == Decimal("850.25")
    assert outcome.options[0].legs[0].destination_airport == "LHR"
    filters = client.calls[0]
    assert filters.flight_segments[0].departure_airport == [[Airport.JFK, 0]]
    assert filters.flight_segments[0].arrival_airport == [
        [Airport.LHR, 0],
        [Airport.LGW, 0],
    ]


def test_exact_parse_change_is_classified_without_upstream_details() -> None:
    client = FakeFlightClient(SearchParseError("private upstream response"))
    provider = GoogleFlightsFlexibleProvider(
        flight_client_factory=lambda: client, sleeper=lambda _delay: None
    )

    outcome = provider.verify(
        _market(),
        departure_date=date(2027, 1, 10),
        return_date=date(2027, 1, 20),
        max_results=5,
    )

    assert outcome.status is SearchStatus.PROVIDER_CHANGED
    assert "private upstream response" not in (outcome.error_message or "")


def test_provider_rejects_invalid_construction_and_requests() -> None:
    with pytest.raises(ValueError, match="retry_attempts"):
        GoogleFlightsFlexibleProvider(retry_attempts=0)
    with pytest.raises(ValueError, match="retry_base_delay_seconds"):
        GoogleFlightsFlexibleProvider(retry_base_delay_seconds=-1)
    with pytest.raises(ValueError, match="calendar_chunk_days"):
        GoogleFlightsFlexibleProvider(calendar_chunk_days=62)

    provider = GoogleFlightsFlexibleProvider()
    calendar = provider.search_calendar(
        _market(), start_date=date(2027, 2, 1), end_date=date(2027, 1, 1)
    )
    exact = provider.verify(
        _market(),
        departure_date=date(2027, 1, 20),
        return_date=date(2027, 1, 10),
        max_results=0,
    )

    assert calendar.status is SearchStatus.INVALID_REQUEST
    assert exact.status is SearchStatus.INVALID_REQUEST


def test_empty_calendar_and_exact_results_remain_empty() -> None:
    calendar_client = FakeCalendarClient([None])
    flight_client = FakeFlightClient(None)
    provider = GoogleFlightsFlexibleProvider(
        calendar_client_factory=lambda: calendar_client,
        flight_client_factory=lambda: flight_client,
    )

    calendar = provider.search_calendar(
        _market(), start_date=date(2027, 1, 1), end_date=date(2027, 1, 20)
    )
    exact = provider.verify(
        _market(),
        departure_date=date(2027, 1, 10),
        return_date=date(2027, 1, 20),
        max_results=5,
    )

    assert calendar.status is SearchStatus.EMPTY
    assert calendar.request_count == 1
    assert exact.status is SearchStatus.EMPTY


def test_calendar_retry_uses_bounded_backoff() -> None:
    client = FakeCalendarClient([TimeoutError(), [_date_fare("2027-01-10", "2027-01-20", 900)]])
    delays: list[float] = []
    provider = GoogleFlightsFlexibleProvider(
        retry_attempts=2,
        retry_base_delay_seconds=2,
        calendar_client_factory=lambda: client,
        sleeper=delays.append,
    )

    outcome = provider.search_calendar(
        _market(), start_date=date(2027, 1, 1), end_date=date(2027, 1, 20)
    )

    assert outcome.status is SearchStatus.SUCCESS
    assert outcome.request_count == 2
    assert delays == [2]


def test_exact_exhausted_retry_is_temporary_and_malformed_rows_are_provider_change() -> None:
    failed_client = FakeFlightClient(TimeoutError())
    failed = GoogleFlightsFlexibleProvider(
        retry_attempts=2,
        flight_client_factory=lambda: failed_client,
        sleeper=lambda _delay: None,
    ).verify(
        _market(),
        departure_date=date(2027, 1, 10),
        return_date=date(2027, 1, 20),
        max_results=5,
    )
    malformed = GoogleFlightsFlexibleProvider(
        flight_client_factory=lambda: FakeFlightClient([object()])
    ).verify(
        _market(),
        departure_date=date(2027, 1, 10),
        return_date=date(2027, 1, 20),
        max_results=5,
    )

    assert failed.status is SearchStatus.TEMPORARY_FAILURE
    assert failed.error_code == "TimeoutError"
    assert malformed.status is SearchStatus.PROVIDER_CHANGED

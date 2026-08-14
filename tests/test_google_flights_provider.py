from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fli.models import Airline, Airport, FlightResult
from fli.models import FlightLeg as FliFlightLeg
from fli.search.flights import SearchParseError

from flyclub.models import (
    CabinClass,
    MaxStops,
    OriginRole,
    RouteDefinition,
    SearchStatus,
)
from flyclub.providers.google_flights import GoogleFlightsProvider


def make_route(**changes: Any) -> RouteDefinition:
    values: dict[str, Any] = {
        "key": "from_bh-lis-test",
        "origin_group": "from_bh",
        "origin_label": "Belo Horizonte",
        "origin_role": OriginRole.HOME,
        "origin_airports": ("CNF",),
        "positioning_notice": None,
        "destination": "LIS",
        "destination_name": "Lisboa",
        "departure_date": date(2027, 6, 10),
        "return_date": date(2027, 6, 20),
        "passengers": 1,
        "cabin": CabinClass.ECONOMY,
        "currency": "BRL",
        "max_stops": MaxStops.ANY,
        "alert_price": Decimal("3000"),
    }
    values.update(changes)
    return RouteDefinition(**values)


def make_native_journey(
    *,
    origin: Airport,
    destination: Airport,
    airline: Airline,
    flight_number: str,
    departure: datetime,
    arrival: datetime,
    price: float | None,
    stops: int = 0,
) -> FlightResult:
    leg = FliFlightLeg(
        airline=airline,
        flight_number=flight_number,
        departure_airport=origin,
        arrival_airport=destination,
        departure_datetime=departure,
        arrival_datetime=arrival,
        duration=600,
    )
    return FlightResult(
        legs=[leg],
        price=price,
        currency="BRL",
        duration=600,
        stops=stops,
    )


def round_trip(*, return_price: float | None = 3030.0) -> tuple[FlightResult, FlightResult]:
    outbound = make_native_journey(
        origin=Airport.CNF,
        destination=Airport.LIS,
        airline=Airline.LA,
        flight_number="1234",
        departure=datetime(2027, 6, 10, 10, 0),
        arrival=datetime(2027, 6, 10, 20, 0),
        price=3200.0,
        stops=1,
    )
    inbound = make_native_journey(
        origin=Airport.LIS,
        destination=Airport.CNF,
        airline=Airline.TP,
        flight_number="5678",
        departure=datetime(2027, 6, 20, 9, 0),
        arrival=datetime(2027, 6, 20, 19, 0),
        price=return_price,
        stops=0,
    )
    return outbound, inbound


class FakeClient:
    def __init__(
        self,
        responses: Iterator[list[Any] | Exception | None],
        *,
        url: str = "https://www.google.com/travel/flights/booking?tfs=test",
    ) -> None:
        self.responses = responses
        self.url = url
        self.calls: list[dict[str, Any]] = []

    def search(self, filters: Any, **kwargs: Any) -> list[Any] | None:
        self.calls.append({"filters": filters, **kwargs})
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def build_flight_booking_url(self, flight: Any, **kwargs: Any) -> str:
        return self.url


def test_normalizes_round_trip_without_leaking_fli_models() -> None:
    client = FakeClient(iter([[round_trip()]]))
    provider = GoogleFlightsProvider(client_factory=lambda: client)

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.SUCCESS
    assert len(outcome.options) == 1
    option = outcome.options[0]
    assert option.price == Decimal("3030.0")
    assert option.currency == "BRL"
    assert option.stops == 1
    assert option.duration_minutes == 1200
    assert [leg.journey_index for leg in option.legs] == [0, 1]
    assert [leg.airline for leg in option.legs] == ["LA", "TP"]
    assert option.booking_url is None
    assert option.google_flights_url == "https://www.google.com/travel/flights/booking?tfs=test"

    native_filters = client.calls[0]["filters"]
    assert native_filters.passenger_info.adults == 1
    assert native_filters.flight_segments[0].departure_airport == [[Airport.CNF, 0]]
    assert native_filters.flight_segments[1].arrival_airport == [[Airport.CNF, 0]]
    assert client.calls[0]["currency"] == "BRL"


def test_explicit_sao_paulo_airports_are_sent_to_fli() -> None:
    client = FakeClient(iter([None]))
    provider = GoogleFlightsProvider(client_factory=lambda: client)
    route = make_route(origin_airports=("GRU", "VCP", "CGH"))

    outcome = provider.search(route, max_results=5)

    assert outcome.status is SearchStatus.EMPTY
    departure_airports = client.calls[0]["filters"].flight_segments[0].departure_airport
    assert departure_airports == [[Airport.GRU, 0], [Airport.VCP, 0], [Airport.CGH, 0]]


def test_retries_temporary_errors_with_exponential_backoff() -> None:
    client = FakeClient(iter([TimeoutError(), ConnectionError(), [round_trip()]]))
    delays: list[float] = []
    provider = GoogleFlightsProvider(
        client_factory=lambda: client,
        retry_attempts=3,
        retry_base_delay_seconds=2,
        sleeper=delays.append,
    )

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.SUCCESS
    assert len(client.calls) == 3
    assert delays == [2, 4]


def test_exhausted_retry_is_a_temporary_failure() -> None:
    client = FakeClient(iter([TimeoutError(), TimeoutError()]))
    provider = GoogleFlightsProvider(
        client_factory=lambda: client,
        retry_attempts=2,
        sleeper=lambda _: None,
    )

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.TEMPORARY_FAILURE
    assert outcome.error_code == "TimeoutError"
    assert outcome.options == ()


def test_empty_response_after_a_retry_is_not_reported_as_failure() -> None:
    client = FakeClient(iter([TimeoutError(), None]))
    provider = GoogleFlightsProvider(
        client_factory=lambda: client,
        retry_attempts=2,
        sleeper=lambda _: None,
    )

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.EMPTY
    assert len(client.calls) == 2


def test_parse_error_is_reported_as_provider_change_without_retry() -> None:
    client = FakeClient(iter([SearchParseError("private upstream detail")]))
    provider = GoogleFlightsProvider(client_factory=lambda: client, sleeper=lambda _: None)

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.PROVIDER_CHANGED
    assert outcome.error_code == "SEARCH_PARSE_ERROR"
    assert "private upstream detail" not in (outcome.error_message or "")
    assert len(client.calls) == 1


def test_result_without_total_price_is_not_invented() -> None:
    client = FakeClient(iter([[round_trip(return_price=None)]]))
    provider = GoogleFlightsProvider(client_factory=lambda: client)

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.PROVIDER_CHANGED
    assert outcome.error_code == "NO_NORMALIZABLE_RESULTS"


def test_one_malformed_result_does_not_discard_valid_options() -> None:
    client = FakeClient(iter([[object(), round_trip()]]))
    provider = GoogleFlightsProvider(client_factory=lambda: client)

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.SUCCESS
    assert len(outcome.options) == 1


def test_invalid_url_is_discarded() -> None:
    client = FakeClient(iter([[round_trip()]]), url="javascript:alert(1)")
    provider = GoogleFlightsProvider(client_factory=lambda: client)

    outcome = provider.search(make_route(), max_results=5)

    assert outcome.status is SearchStatus.SUCCESS
    assert outcome.options[0].google_flights_url is None


def test_invalid_route_is_reported_before_network() -> None:
    client = FakeClient(iter([[round_trip()]]))
    provider = GoogleFlightsProvider(client_factory=lambda: client)

    outcome = provider.search(make_route(origin_airports=("INVALID",)), max_results=5)

    assert outcome.status is SearchStatus.INVALID_REQUEST
    assert client.calls == []

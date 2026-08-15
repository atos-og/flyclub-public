"""Google Flights provider implemented behind Fly Club's provider boundary."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlparse

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.models import (
    MaxStops as FliMaxStops,
)
from fli.search import SearchFlights
from fli.search.flights import SearchParseError

from flyclub.models import (
    CabinClass,
    FlightLeg,
    FlightOption,
    MaxStops,
    RouteDefinition,
    SearchOutcome,
    SearchStatus,
)


class _SearchClient(Protocol):
    def search(
        self,
        filters: FlightSearchFilters,
        top_n: int = 5,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[Any] | None: ...

    def build_flight_booking_url(
        self,
        flight: Any,
        *,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> str: ...


_CABIN_MAP = {
    CabinClass.ECONOMY: SeatType.ECONOMY,
    CabinClass.PREMIUM_ECONOMY: SeatType.PREMIUM_ECONOMY,
    CabinClass.BUSINESS: SeatType.BUSINESS,
    CabinClass.FIRST: SeatType.FIRST,
}

_STOPS_MAP = {
    MaxStops.ANY: FliMaxStops.ANY,
    MaxStops.NON_STOP: FliMaxStops.NON_STOP,
    MaxStops.ONE_OR_FEWER_STOPS: FliMaxStops.ONE_STOP_OR_FEWER,
    MaxStops.TWO_OR_FEWER_STOPS: FliMaxStops.TWO_OR_FEWER_STOPS,
}

_LOGGER = logging.getLogger(__name__)
_ROUND_TRIP_PRICE_WARNING_THRESHOLD = Decimal("2")


class GoogleFlightsProvider:
    """Translate Fly Club routes to and from the unofficial `fli` API."""

    name = "google_flights"

    def __init__(
        self,
        *,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 2,
        language: str = "pt-BR",
        country: str = "BR",
        client_factory: Callable[[], _SearchClient] = SearchFlights,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must not be negative")
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._language = language
        self._country = country
        self._client_factory = client_factory
        self._sleeper = sleeper
        self._round_trip_divergence_warned = False

    def search(self, route: RouteDefinition, *, max_results: int) -> SearchOutcome:
        if max_results < 1:
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.INVALID_REQUEST,
                error_code="INVALID_MAX_RESULTS",
                error_message="max_results must be at least 1",
            )

        try:
            filters = self._build_filters(route)
        except (KeyError, ValueError) as error:
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.INVALID_REQUEST,
                error_code=type(error).__name__,
                error_message="The route could not be represented by the provider",
            )

        raw_results: list[Any] | None = None
        client: _SearchClient | None = None
        last_error_code: str | None = None

        for attempt in range(self._retry_attempts):
            client = self._client_factory()
            try:
                raw_results = client.search(
                    filters,
                    top_n=max_results,
                    currency=route.currency,
                    language=self._language,
                    country=self._country,
                )
                last_error_code = None
                break
            except SearchParseError:
                return SearchOutcome(
                    provider=self.name,
                    status=SearchStatus.PROVIDER_CHANGED,
                    error_code="SEARCH_PARSE_ERROR",
                    error_message="Google Flights returned an unsupported response shape",
                )
            except Exception as error:  # The adapter is the external-library exception boundary.
                last_error_code = type(error).__name__
                if attempt + 1 < self._retry_attempts:
                    delay = self._retry_base_delay_seconds * (2**attempt)
                    self._sleeper(delay)

        if client is None or (raw_results is None and last_error_code is not None):
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.TEMPORARY_FAILURE,
                error_code=last_error_code or "UNKNOWN_PROVIDER_ERROR",
                error_message=f"Provider request failed after {self._retry_attempts} attempts",
            )

        if not raw_results:
            return SearchOutcome(provider=self.name, status=SearchStatus.EMPTY)

        self._round_trip_divergence_warned = False
        options: list[FlightOption] = []
        for raw_result in raw_results:
            try:
                option = self._normalize_option(client, raw_result, route)
            except Exception:  # One malformed external row must not abort normalization of others.
                option = None
            if option is not None:
                options.append(option)

        if not options:
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.PROVIDER_CHANGED,
                error_code="NO_NORMALIZABLE_RESULTS",
                error_message="Provider results did not contain a usable total price and itinerary",
            )

        options.sort(key=lambda option: option.price)
        return SearchOutcome(
            provider=self.name,
            status=SearchStatus.SUCCESS,
            options=tuple(options[:max_results]),
        )

    def _build_filters(self, route: RouteDefinition) -> FlightSearchFilters:
        origin_airports = [[Airport[code], 0] for code in route.origin_airports]
        destination_airports = [[Airport[route.destination], 0]]
        segments = [
            FlightSegment(
                departure_airport=origin_airports,
                arrival_airport=destination_airports,
                travel_date=route.departure_date.isoformat(),
            ),
            FlightSegment(
                departure_airport=destination_airports,
                arrival_airport=origin_airports,
                travel_date=route.return_date.isoformat(),
            ),
        ]
        return FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=route.passengers),
            flight_segments=segments,
            seat_type=_CABIN_MAP[route.cabin],
            stops=_STOPS_MAP[route.max_stops],
            sort_by=SortBy.CHEAPEST,
            show_all_results=False,
        )

    def _normalize_option(
        self, client: _SearchClient, raw_result: Any, route: RouteDefinition
    ) -> FlightOption | None:
        journeys = raw_result if isinstance(raw_result, tuple) else (raw_result,)
        if not journeys:
            return None

        priced_journey = journeys[0]
        price = self._decimal_price(getattr(priced_journey, "price", None))
        if price is None:
            return None

        final_price = self._decimal_price(getattr(journeys[-1], "price", None))
        if final_price is not None:
            difference_percent = abs(price - final_price) / price * Decimal("100")
            if (
                difference_percent > _ROUND_TRIP_PRICE_WARNING_THRESHOLD
                and not self._round_trip_divergence_warned
            ):
                _LOGGER.warning(
                    "Round-trip journey prices diverged by more than 2%; "
                    "the outbound total remains authoritative"
                )
                self._round_trip_divergence_warned = True

        legs: list[FlightLeg] = []
        for journey_index, journey in enumerate(journeys):
            native_legs = getattr(journey, "legs", None)
            if not native_legs:
                return None
            for native_leg in native_legs:
                legs.append(
                    FlightLeg(
                        journey_index=journey_index,
                        origin_airport=self._enum_code(native_leg.departure_airport),
                        destination_airport=self._enum_code(native_leg.arrival_airport),
                        departure_time=native_leg.departure_datetime,
                        arrival_time=native_leg.arrival_datetime,
                        airline=self._enum_code(native_leg.airline),
                        flight_number=native_leg.flight_number,
                    )
                )

        try:
            candidate_url = client.build_flight_booking_url(
                raw_result,
                currency=route.currency,
                language=self._language,
                country=self._country,
            )
        except Exception:
            candidate_url = None

        currency = getattr(priced_journey, "currency", None) or route.currency
        stops = max(int(journey.stops) for journey in journeys)
        duration = sum(int(journey.duration) for journey in journeys)
        return FlightOption(
            price=price,
            currency=str(currency).upper(),
            legs=tuple(legs),
            stops=stops,
            duration_minutes=duration,
            booking_url=None,
            google_flights_url=self._validated_url(candidate_url),
        )

    @staticmethod
    def _decimal_price(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        try:
            price = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return price if price.is_finite() and price > 0 else None

    @staticmethod
    def _enum_code(value: Any) -> str:
        return str(getattr(value, "name", value)).lstrip("_")

    @staticmethod
    def _validated_url(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None

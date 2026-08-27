"""Google Flights calendar and exact verification behind a flexible-market boundary."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlparse

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.models import MaxStops as FliMaxStops
from fli.search import SearchDates, SearchFlights
from fli.search.flights import SearchParseError

from flyclub.flexible_market_models import (
    CalendarFare,
    CalendarSearchOutcome,
    FlexibleMarketDefinition,
)
from flyclub.models import (
    CabinClass,
    FlightLeg,
    FlightOption,
    MaxStops,
    SearchOutcome,
    SearchStatus,
)


class _CalendarClient(Protocol):
    def search(
        self,
        filters: DateSearchFilters,
        currency: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[Any] | None: ...


class _FlightClient(Protocol):
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


class GoogleFlightsFlexibleProvider:
    """Search calendar chunks sequentially and verify shortlisted dates exactly."""

    name = "google_flights_flexible"

    def __init__(
        self,
        *,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 2,
        calendar_chunk_days: int = 61,
        language: str = "pt-BR",
        country: str = "BR",
        calendar_client_factory: Callable[[], _CalendarClient] = SearchDates,
        flight_client_factory: Callable[[], _FlightClient] = SearchFlights,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must not be negative")
        if not 1 <= calendar_chunk_days <= 61:
            raise ValueError("calendar_chunk_days must be between 1 and 61")
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._calendar_chunk_days = calendar_chunk_days
        self._language = language
        self._country = country
        self._calendar_client_factory = calendar_client_factory
        self._flight_client_factory = flight_client_factory
        self._sleeper = sleeper

    def search_calendar(
        self,
        market: FlexibleMarketDefinition,
        *,
        start_date: Any,
        end_date: Any,
    ) -> CalendarSearchOutcome:
        if end_date < start_date:
            return CalendarSearchOutcome(
                provider=self.name,
                status=SearchStatus.INVALID_REQUEST,
                error_code="INVALID_DATE_WINDOW",
                error_message="Calendar date window is reversed",
            )

        collected: dict[tuple[Any, Any], CalendarFare] = {}
        request_count = 0
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + timedelta(days=self._calendar_chunk_days - 1), end_date)
            filters = self._calendar_filters(market, chunk_start, chunk_end)
            raw_results = None
            last_error_code = None
            for attempt in range(self._retry_attempts):
                request_count += 1
                client = self._calendar_client_factory()
                try:
                    raw_results = client.search(
                        filters,
                        currency=market.currency,
                        language=self._language,
                        country=self._country,
                    )
                    last_error_code = None
                    break
                except Exception as error:
                    last_error_code = type(error).__name__
                    if attempt + 1 < self._retry_attempts:
                        self._sleeper(self._retry_base_delay_seconds * (2**attempt))
            if raw_results is None and last_error_code is not None:
                return CalendarSearchOutcome(
                    provider=self.name,
                    status=SearchStatus.TEMPORARY_FAILURE,
                    request_count=request_count,
                    error_code=last_error_code,
                    error_message="Calendar provider request failed after retries",
                )
            for raw in raw_results or []:
                fare = self._normalize_calendar_fare(raw, market)
                if fare is None or not start_date <= fare.departure_date <= end_date:
                    continue
                key = (fare.departure_date, fare.return_date)
                existing = collected.get(key)
                if existing is None or fare.price < existing.price:
                    collected[key] = fare
            chunk_start = chunk_end + timedelta(days=1)

        if not collected:
            return CalendarSearchOutcome(
                provider=self.name,
                status=SearchStatus.EMPTY,
                request_count=request_count,
            )
        fares = tuple(
            sorted(collected.values(), key=lambda fare: (fare.price, fare.departure_date))
        )
        return CalendarSearchOutcome(
            provider=self.name,
            status=SearchStatus.SUCCESS,
            fares=fares,
            request_count=request_count,
        )

    def verify(
        self,
        market: FlexibleMarketDefinition,
        *,
        departure_date: Any,
        return_date: Any,
        max_results: int,
    ) -> SearchOutcome:
        if max_results < 1 or return_date <= departure_date:
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.INVALID_REQUEST,
                error_code="INVALID_VERIFICATION_REQUEST",
                error_message="Exact verification parameters are invalid",
            )
        filters = self._flight_filters(market, departure_date, return_date)
        raw_results = None
        client = None
        last_error_code = None
        for attempt in range(self._retry_attempts):
            client = self._flight_client_factory()
            try:
                raw_results = client.search(
                    filters,
                    top_n=max_results,
                    currency=market.currency,
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
            except Exception as error:
                last_error_code = type(error).__name__
                if attempt + 1 < self._retry_attempts:
                    self._sleeper(self._retry_base_delay_seconds * (2**attempt))
        if client is None or (raw_results is None and last_error_code is not None):
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.TEMPORARY_FAILURE,
                error_code=last_error_code or "UNKNOWN_PROVIDER_ERROR",
                error_message="Exact provider request failed after retries",
            )
        if not raw_results:
            return SearchOutcome(provider=self.name, status=SearchStatus.EMPTY)
        options = tuple(
            option
            for option in (self._normalize_option(client, raw, market) for raw in raw_results)
            if option is not None
        )
        if not options:
            return SearchOutcome(
                provider=self.name,
                status=SearchStatus.PROVIDER_CHANGED,
                error_code="NO_NORMALIZABLE_RESULTS",
                error_message="Exact results did not contain a usable itinerary",
            )
        return SearchOutcome(
            provider=self.name,
            status=SearchStatus.SUCCESS,
            options=tuple(sorted(options, key=lambda option: option.price)[:max_results]),
        )

    @staticmethod
    def _airport_list(codes: tuple[str, ...]) -> list[list[object]]:
        return [[Airport[code], 0] for code in codes]

    def _calendar_filters(
        self, market: FlexibleMarketDefinition, start_date: Any, end_date: Any
    ) -> DateSearchFilters:
        origins = self._airport_list(market.origin_airports)
        destinations = self._airport_list(market.destination_airports)
        return_date = start_date + timedelta(days=market.trip_duration_days)
        return DateSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=market.passengers),
            flight_segments=[
                FlightSegment(
                    departure_airport=origins,
                    arrival_airport=destinations,
                    travel_date=start_date.isoformat(),
                ),
                FlightSegment(
                    departure_airport=destinations,
                    arrival_airport=origins,
                    travel_date=return_date.isoformat(),
                ),
            ],
            stops=_STOPS_MAP[market.max_stops],
            seat_type=_CABIN_MAP[market.cabin],
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
            duration=market.trip_duration_days,
        )

    def _flight_filters(
        self, market: FlexibleMarketDefinition, departure_date: Any, return_date: Any
    ) -> FlightSearchFilters:
        origins = self._airport_list(market.origin_airports)
        destinations = self._airport_list(market.destination_airports)
        return FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=market.passengers),
            flight_segments=[
                FlightSegment(
                    departure_airport=origins,
                    arrival_airport=destinations,
                    travel_date=departure_date.isoformat(),
                ),
                FlightSegment(
                    departure_airport=destinations,
                    arrival_airport=origins,
                    travel_date=return_date.isoformat(),
                ),
            ],
            seat_type=_CABIN_MAP[market.cabin],
            stops=_STOPS_MAP[market.max_stops],
            sort_by=SortBy.CHEAPEST,
            show_all_results=False,
        )

    @classmethod
    def _normalize_calendar_fare(
        cls, raw: Any, market: FlexibleMarketDefinition
    ) -> CalendarFare | None:
        dates = getattr(raw, "date", ())
        if not dates or len(dates) != 2:
            return None
        price = cls._decimal_price(getattr(raw, "price", None))
        if price is None:
            return None
        departure = dates[0].date() if hasattr(dates[0], "date") else dates[0]
        returning = dates[1].date() if hasattr(dates[1], "date") else dates[1]
        if returning - departure != timedelta(days=market.trip_duration_days):
            return None
        return CalendarFare(
            departure_date=departure,
            return_date=returning,
            price=price,
            currency=str(getattr(raw, "currency", None) or market.currency).upper(),
        )

    def _normalize_option(
        self, client: _FlightClient, raw_result: Any, market: FlexibleMarketDefinition
    ) -> FlightOption | None:
        journeys = raw_result if isinstance(raw_result, tuple) else (raw_result,)
        if not journeys:
            return None
        price = self._decimal_price(getattr(journeys[0], "price", None))
        if price is None:
            return None
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
                currency=market.currency,
                language=self._language,
                country=self._country,
            )
        except Exception:
            candidate_url = None
        return FlightOption(
            price=price,
            currency=str(getattr(journeys[0], "currency", None) or market.currency).upper(),
            legs=tuple(legs),
            stops=max(int(journey.stops) for journey in journeys),
            duration_minutes=sum(int(journey.duration) for journey in journeys),
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

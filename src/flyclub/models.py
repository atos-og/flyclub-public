"""Provider-neutral domain models used throughout Fly Club."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class CabinClass(StrEnum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class MaxStops(StrEnum):
    ANY = "ANY"
    NON_STOP = "NON_STOP"
    ONE_OR_FEWER_STOPS = "ONE_OR_FEWER_STOPS"
    TWO_OR_FEWER_STOPS = "TWO_OR_FEWER_STOPS"


class OriginRole(StrEnum):
    HOME = "HOME"
    POSITIONING = "POSITIONING"


class SearchStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PROVIDER_CHANGED = "PROVIDER_CHANGED"
    INVALID_REQUEST = "INVALID_REQUEST"


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    """A comparable route definition generated from configuration."""

    key: str
    origin_group: str
    origin_label: str
    origin_role: OriginRole
    origin_airports: tuple[str, ...]
    positioning_notice: str | None
    destination: str
    destination_name: str | None
    departure_date: date
    return_date: date
    passengers: int
    cabin: CabinClass
    currency: str
    max_stops: MaxStops
    alert_price: Decimal | None


@dataclass(frozen=True, slots=True)
class FlightLeg:
    journey_index: int
    origin_airport: str
    destination_airport: str
    departure_time: datetime | None
    arrival_time: datetime | None
    airline: str | None
    flight_number: str | None


@dataclass(frozen=True, slots=True)
class FlightOption:
    """One normalized itinerary returned by any flight provider."""

    price: Decimal
    currency: str
    legs: tuple[FlightLeg, ...]
    stops: int | None = None
    duration_minutes: int | None = None
    booking_url: str | None = None
    google_flights_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Typed provider result that keeps empty searches separate from failures."""

    provider: str
    status: SearchStatus
    options: tuple[FlightOption, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.status is SearchStatus.SUCCESS and not self.options:
            raise ValueError("A successful search must contain at least one option")
        if self.status is not SearchStatus.SUCCESS and self.options:
            raise ValueError("Only a successful search may contain flight options")


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One prior best-price observation in a comparable route series."""

    price: Decimal
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class OriginPriceComparison:
    """Best comparable HOME-origin fare found in the same monitor run."""

    reference_origin: str
    reference_price: Decimal

    def __post_init__(self) -> None:
        if not self.reference_origin.strip():
            raise ValueError("reference_origin must not be empty")
        if not isinstance(self.reference_price, Decimal):
            raise TypeError("reference_price must use Decimal")
        if self.reference_price <= 0 or not self.reference_price.is_finite():
            raise ValueError("reference_price must be finite and greater than zero")

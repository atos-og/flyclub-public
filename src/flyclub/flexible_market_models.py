"""Provider-neutral models for rolling flexible-market searches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from flyclub.models import CabinClass, MaxStops, SearchStatus


@dataclass(frozen=True, slots=True)
class FlexibleMarketDefinition:
    key: str
    label: str
    origin_airports: tuple[str, ...]
    destination_airports: tuple[str, ...]
    trip_duration_days: int
    passengers: int
    cabin: CabinClass
    currency: str
    max_stops: MaxStops
    minimum_days_ahead: int
    maximum_days_ahead: int
    score_threshold_2026: int
    score_threshold_future: int
    travel_window_start: date | None = None
    travel_window_end: date | None = None


@dataclass(frozen=True, slots=True)
class CalendarFare:
    departure_date: date
    return_date: date
    price: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        if not isinstance(self.price, Decimal):
            raise TypeError("price must use Decimal")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be finite and positive")


@dataclass(frozen=True, slots=True)
class CalendarSearchOutcome:
    provider: str
    status: SearchStatus
    fares: tuple[CalendarFare, ...] = ()
    request_count: int = 0
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.request_count < 0:
            raise ValueError("request_count must not be negative")
        if self.status is SearchStatus.SUCCESS and not self.fares:
            raise ValueError("A successful calendar search must contain fares")
        if self.status is not SearchStatus.SUCCESS and self.fares:
            raise ValueError("Only a successful calendar search may contain fares")


@dataclass(frozen=True, slots=True)
class FlexibleMarketPeriod:
    key: str
    label: str
    start_date: date
    end_date: date
    minimum_deal_score: int

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("period dates are reversed")
        if not 0 <= self.minimum_deal_score <= 100:
            raise ValueError("minimum_deal_score must be between 0 and 100")


def market_definition(config: object) -> FlexibleMarketDefinition:
    """Convert a validated configuration object without coupling consumers to Pydantic."""

    return FlexibleMarketDefinition(
        key=config.id,
        label=config.label,
        origin_airports=config.origin_airports,
        destination_airports=config.destination_airports,
        trip_duration_days=config.trip_duration_days,
        passengers=config.passengers,
        cabin=config.cabin,
        currency=config.currency,
        max_stops=config.max_stops,
        minimum_days_ahead=config.minimum_days_ahead,
        maximum_days_ahead=config.maximum_days_ahead,
        score_threshold_2026=config.score_threshold_2026,
        score_threshold_future=config.score_threshold_future,
        travel_window_start=config.travel_window_start,
        travel_window_end=config.travel_window_end,
    )

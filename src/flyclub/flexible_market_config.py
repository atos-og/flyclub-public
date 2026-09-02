"""Private configuration for rolling flexible-market searches."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from flyclub.models import CabinClass, MaxStops

FLEXIBLE_MARKETS_YAML_ENV = "FLYCLUB_FLEXIBLE_MARKETS_YAML"
FLEXIBLE_MARKETS_CONFIG_PATH_ENV = "FLYCLUB_FLEXIBLE_MARKETS_CONFIG_PATH"
DEFAULT_FLEXIBLE_MARKETS_PATH = Path("config/flexible-markets.yaml")

_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
_MARKET_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class FlexibleMarketConfigError(ValueError):
    """Raised without echoing private configuration values."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalize_iata_list(value: Any) -> Any:
    if not isinstance(value, (list, tuple)):
        return value
    return tuple(str(item).strip().upper() for item in value)


class FlexibleMarket(_StrictModel):
    id: str
    label: str = Field(min_length=1, max_length=80)
    origin_airports: tuple[str, ...] = Field(min_length=1)
    destination_airports: tuple[str, ...] = Field(min_length=1)
    trip_duration_days: int = Field(default=10, ge=1, le=30)
    passengers: int = Field(default=1, ge=1, le=9)
    cabin: CabinClass = CabinClass.ECONOMY
    currency: str = "BRL"
    max_stops: MaxStops = MaxStops.ANY
    minimum_days_ahead: int = Field(default=14, ge=1, le=304)
    maximum_days_ahead: int = Field(default=305, ge=2, le=305)
    score_threshold_2026: int = Field(default=80, ge=60, le=100)
    score_threshold_future: int = Field(default=75, ge=60, le=100)
    travel_window_start: date | None = None
    travel_window_end: date | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _MARKET_ID_PATTERN.fullmatch(normalized):
            raise ValueError("must use lowercase snake_case")
        return normalized

    @field_validator("origin_airports", "destination_airports", mode="before")
    @classmethod
    def normalize_airports(cls, value: Any) -> Any:
        return _normalize_iata_list(value)

    @field_validator("origin_airports", "destination_airports")
    @classmethod
    def validate_airports(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _IATA_PATTERN.fullmatch(code) for code in value):
            raise ValueError("must contain only three-letter IATA codes")
        if len(set(value)) != len(value):
            raise ValueError("must not contain duplicate airports")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not _IATA_PATTERN.fullmatch(value):
            raise ValueError("must be a three-letter ISO 4217 code")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> FlexibleMarket:
        if self.minimum_days_ahead >= self.maximum_days_ahead:
            raise ValueError("minimum_days_ahead must be lower than maximum_days_ahead")
        if (self.travel_window_start is None) != (self.travel_window_end is None):
            raise ValueError("travel_window_start and travel_window_end must be provided together")
        if self.travel_window_start is not None and self.travel_window_end is not None:
            available_days = (self.travel_window_end - self.travel_window_start).days
            if available_days < self.trip_duration_days:
                raise ValueError("travel window must contain at least one complete trip")
        return self


class FlexibleMarketSettings(_StrictModel):
    markets: tuple[FlexibleMarket, ...] = Field(min_length=1)
    retry_attempts: int = Field(default=3, ge=1, le=5)
    retry_base_delay_seconds: Decimal = Field(default=Decimal("2"), ge=0, le=30)
    calendar_chunk_days: int = Field(default=61, ge=1, le=61)
    verification_candidates_per_period: int = Field(default=2, ge=1, le=3)
    verification_results: int = Field(default=5, ge=1, le=10)
    min_score_samples: int = Field(default=12, ge=2)
    low_confidence_max_samples: int = Field(default=30, ge=2)
    moderate_confidence_max_samples: int = Field(default=100, ge=3)
    cooldown_hours: int = Field(default=24, ge=0, le=168)
    resend_min_drop_amount: Decimal = Field(default=Decimal("100"), ge=0)
    resend_min_drop_percent: Decimal = Field(default=Decimal("5"), ge=0, le=100)

    @model_validator(mode="after")
    def validate_settings(self) -> FlexibleMarketSettings:
        ids = [market.id for market in self.markets]
        if len(ids) != len(set(ids)):
            raise ValueError("market IDs must be unique")
        if self.min_score_samples > self.low_confidence_max_samples:
            raise ValueError("min_score_samples must not exceed low-confidence maximum")
        if self.low_confidence_max_samples >= self.moderate_confidence_max_samples:
            raise ValueError("confidence thresholds must be strictly increasing")
        return self


def _format_validation_error(error: ValidationError) -> str:
    messages: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "configuration"
        messages.append(f"{location}: {item['msg']}")
    return "; ".join(messages)


def load_flexible_market_text(content: str) -> FlexibleMarketSettings:
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise FlexibleMarketConfigError("Invalid YAML syntax") from error
    if not isinstance(raw, dict):
        raise FlexibleMarketConfigError("The configuration root must be a YAML mapping")
    try:
        return FlexibleMarketSettings.model_validate(raw)
    except ValidationError as error:
        raise FlexibleMarketConfigError(_format_validation_error(error)) from error


def load_flexible_market_config(path: str | Path | None = None) -> FlexibleMarketSettings:
    secret_content = os.environ.get(FLEXIBLE_MARKETS_YAML_ENV)
    if secret_content:
        return load_flexible_market_text(secret_content)
    selected_path = Path(
        path or os.environ.get(FLEXIBLE_MARKETS_CONFIG_PATH_ENV) or DEFAULT_FLEXIBLE_MARKETS_PATH
    )
    try:
        content = selected_path.read_text(encoding="utf-8")
    except OSError as error:
        raise FlexibleMarketConfigError(
            f"Unable to read configuration file: {selected_path}"
        ) from error
    return load_flexible_market_text(content)


def flexible_market_fingerprint(settings: FlexibleMarketSettings) -> str:
    canonical = json.dumps(
        settings.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

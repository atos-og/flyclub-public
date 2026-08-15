"""Safe, validated configuration loading for Fly Club."""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from flyclub.models import CabinClass, MaxStops, OriginRole

ROUTES_YAML_ENV = "FLYCLUB_ROUTES_YAML"
CONFIG_PATH_ENV = "FLYCLUB_CONFIG_PATH"
DEFAULT_CONFIG_PATH = Path("config/routes.yaml")

_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
_GROUP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ConfigError(ValueError):
    """Raised for configuration errors without exposing the original YAML."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _uppercase(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _validate_iata(value: str) -> str:
    normalized = _uppercase(value)
    if not isinstance(normalized, str) or not _IATA_PATTERN.fullmatch(normalized):
        raise ValueError("must be a three-letter IATA code")
    return normalized


class TripConfig(StrictModel):
    departure_date: date
    return_date: date
    passengers: int = Field(default=1, ge=1, le=9)
    cabin: CabinClass = CabinClass.ECONOMY
    currency: str = "BRL"
    max_stops: MaxStops = MaxStops.ANY

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> Any:
        return _uppercase(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not _IATA_PATTERN.fullmatch(value):
            raise ValueError("must be a three-letter ISO 4217 code")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> TripConfig:
        if self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        return self


class OriginGroupConfig(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    role: OriginRole
    airports: tuple[str, ...] = Field(min_length=1)
    notice: str | None = Field(default=None, max_length=240)

    @field_validator("airports", mode="before")
    @classmethod
    def normalize_airports(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        return tuple(_validate_iata(item) for item in value)

    @model_validator(mode="after")
    def validate_group(self) -> OriginGroupConfig:
        if len(set(self.airports)) != len(self.airports):
            raise ValueError("airports must not contain duplicates")
        if self.role is OriginRole.POSITIONING and not self.notice:
            raise ValueError("a POSITIONING origin requires a notice")
        return self


class DestinationConfig(StrictModel):
    code: str
    name: str | None = Field(default=None, max_length=80)
    alert_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any) -> Any:
        return _validate_iata(value)


class MonitorConfig(StrictModel):
    interval_hours: int = Field(default=3, ge=1, le=24)
    max_results_per_route: int = Field(default=5, ge=1, le=30)
    retry_attempts: int = Field(default=3, ge=1, le=5)
    retry_base_delay_seconds: int = Field(default=2, ge=1, le=30)


class DealScoreWeightsConfig(StrictModel):
    percentile: int = Field(default=40, ge=0, le=100)
    median_discount: int = Field(default=25, ge=0, le=100)
    recorded_low_proximity: int = Field(default=15, ge=0, le=100)
    recent_drop: int = Field(default=10, ge=0, le=100)
    trend: int = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self) -> DealScoreWeightsConfig:
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Deal Score weights must total 100")
        return self


class AnalysisConfig(StrictModel):
    min_score_samples: int = Field(default=12, ge=2)
    low_confidence_max_samples: int = Field(default=30, ge=2)
    moderate_confidence_max_samples: int = Field(default=100, ge=3)
    deal_score_weights: DealScoreWeightsConfig = DealScoreWeightsConfig()

    @model_validator(mode="after")
    def validate_thresholds(self) -> AnalysisConfig:
        if self.min_score_samples > self.low_confidence_max_samples:
            raise ValueError("min_score_samples must not exceed the low-confidence maximum")
        if self.low_confidence_max_samples >= self.moderate_confidence_max_samples:
            raise ValueError("confidence thresholds must be strictly increasing")
        return self


class AlertConfig(StrictModel):
    exceptional_score: int = Field(default=90, ge=0, le=100)
    cooldown_hours: int = Field(default=24, ge=0)
    min_drop_amount: Decimal = Field(default=Decimal("100"), ge=0)
    min_drop_percent: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    positioning_context_min_savings: Decimal = Field(default=Decimal("100"), ge=0)


class HealthConfig(StrictModel):
    problem_alert_after_runs: int = Field(default=3, ge=1, le=24)


class FlyClubConfig(StrictModel):
    trip: TripConfig
    origins: dict[str, OriginGroupConfig] = Field(min_length=1)
    destinations: tuple[DestinationConfig, ...] = Field(min_length=1)
    monitor: MonitorConfig = MonitorConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    alerts: AlertConfig = AlertConfig()
    health: HealthConfig = HealthConfig()

    @field_validator("origins")
    @classmethod
    def validate_origin_ids(
        cls, value: dict[str, OriginGroupConfig]
    ) -> dict[str, OriginGroupConfig]:
        invalid = [key for key in value if not _GROUP_ID_PATTERN.fullmatch(key)]
        if invalid:
            raise ValueError("origin IDs must use lowercase snake_case")
        return value

    @model_validator(mode="after")
    def validate_destinations(self) -> FlyClubConfig:
        codes = [destination.code for destination in self.destinations]
        if len(set(codes)) != len(codes):
            raise ValueError("destinations must not contain duplicate IATA codes")
        return self


def _format_validation_error(error: ValidationError) -> str:
    messages: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "configuration"
        messages.append(f"{location}: {item['msg']}")
    return "; ".join(messages)


def load_config_text(content: str) -> FlyClubConfig:
    """Parse YAML content without including its values in raised errors."""

    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ConfigError("Invalid YAML syntax") from error

    if not isinstance(raw, dict):
        raise ConfigError("The configuration root must be a YAML mapping")

    try:
        return FlyClubConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(_format_validation_error(error)) from error


def load_config(path: str | Path | None = None) -> FlyClubConfig:
    """Load private YAML from an environment secret or an ignored local file.

    Precedence: FLYCLUB_ROUTES_YAML, explicit path, FLYCLUB_CONFIG_PATH,
    then config/routes.yaml.
    """

    secret_content = os.environ.get(ROUTES_YAML_ENV)
    if secret_content:
        return load_config_text(secret_content)

    selected_path = Path(path or os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)
    try:
        content = selected_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"Unable to read configuration file: {selected_path}") from error
    return load_config_text(content)

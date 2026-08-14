"""Expand high-level Fly Club configuration into comparable routes."""

from __future__ import annotations

import hashlib
import json

from flyclub.config import FlyClubConfig
from flyclub.models import RouteDefinition


def config_fingerprint(config: FlyClubConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _route_fingerprint_payload(
    config: FlyClubConfig, origin_group: str, destination: str
) -> dict[str, object]:
    origin = config.origins[origin_group]
    trip = config.trip
    return {
        "origin_group": origin_group,
        "origin_airports": sorted(origin.airports),
        "destination": destination,
        "departure_date": trip.departure_date.isoformat(),
        "return_date": trip.return_date.isoformat(),
        "passengers": trip.passengers,
        "cabin": trip.cabin.value,
        "currency": trip.currency,
        "max_stops": trip.max_stops.value,
    }


def _route_key(config: FlyClubConfig, origin_group: str, destination: str) -> str:
    payload = json.dumps(
        _route_fingerprint_payload(config, origin_group, destination),
        sort_keys=True,
        separators=(",", ":"),
    )
    suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{origin_group}-{destination.lower()}-{suffix}"


def plan_routes(config: FlyClubConfig) -> tuple[RouteDefinition, ...]:
    routes: list[RouteDefinition] = []
    for origin_group, origin in config.origins.items():
        for destination in config.destinations:
            routes.append(
                RouteDefinition(
                    key=_route_key(config, origin_group, destination.code),
                    origin_group=origin_group,
                    origin_label=origin.label,
                    origin_role=origin.role,
                    origin_airports=origin.airports,
                    positioning_notice=origin.notice,
                    destination=destination.code,
                    destination_name=destination.name,
                    departure_date=config.trip.departure_date,
                    return_date=config.trip.return_date,
                    passengers=config.trip.passengers,
                    cabin=config.trip.cabin,
                    currency=config.trip.currency,
                    max_stops=config.trip.max_stops,
                    alert_price=destination.alert_price,
                )
            )
    return tuple(routes)

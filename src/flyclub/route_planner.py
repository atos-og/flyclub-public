"""Expand high-level Fly Club configuration into comparable routes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

from flyclub.config import FlyClubConfig
from flyclub.models import RouteDefinition, RouteKind

FLEXIBLE_DATE_OFFSETS = (-3, -2, -1, 1, 2, 3)


def config_fingerprint(config: FlyClubConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _route_fingerprint_payload(
    config: FlyClubConfig,
    origin_group: str,
    destination: str,
    *,
    departure_offset_days: int = 0,
    kind: RouteKind = RouteKind.MAIN,
) -> dict[str, object]:
    origin = config.origins[origin_group]
    trip = config.trip
    payload: dict[str, object] = {
        "origin_group": origin_group,
        "origin_airports": sorted(origin.airports),
        "destination": destination,
        "departure_date": (trip.departure_date + timedelta(days=departure_offset_days)).isoformat(),
        "return_date": (trip.return_date + timedelta(days=departure_offset_days)).isoformat(),
        "passengers": trip.passengers,
        "cabin": trip.cabin.value,
        "currency": trip.currency,
        "max_stops": trip.max_stops.value,
    }
    if kind is not RouteKind.MAIN:
        payload["kind"] = kind.value
    return payload


def _route_key(
    config: FlyClubConfig,
    origin_group: str,
    destination: str,
    *,
    departure_offset_days: int = 0,
    kind: RouteKind = RouteKind.MAIN,
) -> str:
    payload = json.dumps(
        _route_fingerprint_payload(
            config,
            origin_group,
            destination,
            departure_offset_days=departure_offset_days,
            kind=kind,
        ),
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
                    positioning_cost_estimate=origin.positioning_cost_estimate,
                )
            )
    return tuple(routes)


def plan_flexible_date_routes(
    config: FlyClubConfig,
    *,
    offsets: tuple[int, ...] = FLEXIBLE_DATE_OFFSETS,
) -> tuple[RouteDefinition, ...]:
    """Shift the complete trip while preserving duration and statistical isolation."""

    if not offsets or 0 in offsets or len(set(offsets)) != len(offsets):
        raise ValueError("flexible date offsets must be unique, non-zero, and non-empty")
    routes: list[RouteDefinition] = []
    for base_route in plan_routes(config):
        for offset in offsets:
            routes.append(
                replace(
                    base_route,
                    key=_route_key(
                        config,
                        base_route.origin_group,
                        base_route.destination,
                        departure_offset_days=offset,
                        kind=RouteKind.FLEXIBLE,
                    ),
                    departure_date=base_route.departure_date + timedelta(days=offset),
                    return_date=base_route.return_date + timedelta(days=offset),
                    kind=RouteKind.FLEXIBLE,
                )
            )
    return tuple(routes)

"""Command-line entry point for Fly Club."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from flyclub.config import ConfigError, load_config
from flyclub.models import RouteDefinition, SearchOutcome, SearchStatus
from flyclub.route_planner import config_fingerprint, plan_routes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub", description="Fly Club flight monitor")
    parser.add_argument("--config", help="Path to an ignored local routes YAML file")
    parser.add_argument(
        "--show-routes",
        action="store_true",
        help="Show configured route endpoints (avoid in shared logs)",
    )
    parser.add_argument(
        "--search-route",
        metavar="ORIGIN_GROUP:DESTINATION",
        help="Run one explicit live provider search (may reveal trip data in local output)",
    )
    return parser


def _select_route(routes: tuple[RouteDefinition, ...], selector: str) -> RouteDefinition:
    try:
        origin_group, destination = selector.split(":", maxsplit=1)
    except ValueError as error:
        raise ConfigError("--search-route must use ORIGIN_GROUP:DESTINATION") from error
    normalized_destination = destination.strip().upper()
    matches = [
        route
        for route in routes
        if route.origin_group == origin_group.strip()
        and route.destination == normalized_destination
    ]
    if len(matches) != 1:
        raise ConfigError("--search-route does not match exactly one configured route")
    return matches[0]


def _print_search_outcome(route: RouteDefinition, outcome: SearchOutcome) -> None:
    print(f"Provider status: {outcome.status.value}")
    if outcome.status is SearchStatus.EMPTY:
        print("No flight options were returned.")
        return
    if outcome.status is not SearchStatus.SUCCESS:
        print(f"Provider error: {outcome.error_code or 'UNKNOWN'}")
        return

    print(f"Options: {len(outcome.options)}")
    for index, option in enumerate(outcome.options, start=1):
        stops = "unknown stops" if option.stops is None else f"max {option.stops} stop(s)"
        print(
            f"{index}. {option.currency} {option.price} | "
            f"{route.origin_group} -> {route.destination} | {stops}"
        )
        if option.google_flights_url:
            print(f"   {option.google_flights_url}")


def cli(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    routes = plan_routes(config)

    if args.search_route:
        try:
            route = _select_route(routes, args.search_route)
        except ConfigError as error:
            print(f"Configuration error: {error}", file=sys.stderr)
            return 2

        from flyclub.providers.google_flights import GoogleFlightsProvider

        provider = GoogleFlightsProvider(
            retry_attempts=config.monitor.retry_attempts,
            retry_base_delay_seconds=config.monitor.retry_base_delay_seconds,
        )
        outcome = provider.search(route, max_results=config.monitor.max_results_per_route)
        _print_search_outcome(route, outcome)
        return 0 if outcome.status in {SearchStatus.SUCCESS, SearchStatus.EMPTY} else 1

    print("Fly Club configuration is valid.")
    print(f"Origin groups: {len(config.origins)}")
    print(f"Destinations: {len(config.destinations)}")
    print(f"Planned routes: {len(routes)}")
    print(f"Config fingerprint: {config_fingerprint(config)[:12]}")

    if args.show_routes:
        for route in routes:
            airports = ",".join(route.origin_airports)
            print(f"- {route.origin_group} ({airports}) -> {route.destination}")
    return 0

"""Command-line entry point for Fly Club."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from flyclub.config import ConfigError, FlyClubConfig, load_config
from flyclub.models import RouteDefinition, SearchOutcome, SearchStatus
from flyclub.route_planner import config_fingerprint, plan_routes
from flyclub.storage.postgres import RunStatus, StorageError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub", description="Fly Club flight monitor")
    parser.add_argument("--config", help="Path to an ignored local routes YAML file")
    parser.add_argument(
        "--show-routes",
        action="store_true",
        help="Show configured route endpoints (avoid in shared logs)",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--search-route",
        metavar="ORIGIN_GROUP:DESTINATION",
        help="Run one explicit live provider search (may reveal trip data in local output)",
    )
    action.add_argument(
        "--monitor",
        action="store_true",
        help="Search every configured route sequentially without printing route details",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --monitor, run provider searches without PostgreSQL persistence",
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


def _run_all_routes(
    config: FlyClubConfig, routes: tuple[RouteDefinition, ...], *, dry_run: bool
) -> int:
    from flyclub.alerts.engine import AlertPolicy
    from flyclub.alerts.service import AlertCoordinator
    from flyclub.alerts.telegram import TelegramClient
    from flyclub.analysis.deal_score import DealScoreWeights
    from flyclub.analysis.evaluator import AnalysisPolicy, PersistedPriceAnalyzer
    from flyclub.monitor import run_monitor
    from flyclub.providers.google_flights import GoogleFlightsProvider
    from flyclub.storage.postgres import PostgresRepository

    provider = GoogleFlightsProvider(
        retry_attempts=config.monitor.retry_attempts,
        retry_base_delay_seconds=config.monitor.retry_base_delay_seconds,
    )
    repository = None if dry_run else PostgresRepository.from_env()
    analyzer = None
    alert_handler = None
    if repository is not None:
        configured_weights = config.analysis.deal_score_weights
        analyzer = PersistedPriceAnalyzer(
            repository,
            AnalysisPolicy(
                min_score_samples=config.analysis.min_score_samples,
                low_confidence_max_samples=config.analysis.low_confidence_max_samples,
                moderate_confidence_max_samples=config.analysis.moderate_confidence_max_samples,
                weights=DealScoreWeights(**configured_weights.model_dump()),
            ),
        )
        alert_handler = AlertCoordinator(
            repository,
            TelegramClient.from_env(),
            AlertPolicy(
                exceptional_score=config.alerts.exceptional_score,
                cooldown_hours=config.alerts.cooldown_hours,
                min_drop_amount=config.alerts.min_drop_amount,
                min_drop_percent=config.alerts.min_drop_percent,
                min_score_samples=config.analysis.min_score_samples,
            ),
        )
    summary = run_monitor(
        routes=routes,
        config_fingerprint=config_fingerprint(config),
        provider=provider,
        max_results=config.monitor.max_results_per_route,
        repository=repository,
        analyzer=analyzer,
        alert_handler=alert_handler,
    )
    mode = "dry-run" if dry_run else "persisted"
    print(f"Fly Club monitor finished: {summary.status.value} ({mode}).")
    print(f"Planned routes: {summary.planned_routes}")
    print(f"Successful routes: {summary.successful_routes}")
    print(f"Empty routes: {summary.empty_routes}")
    print(f"Failed routes: {summary.failed_routes}")
    print(f"Analyzed routes: {summary.analyzed_routes}")
    print(f"Alerts sent: {summary.alerts_sent}")
    print(f"Alerts suppressed: {summary.alerts_suppressed}")
    return 0 if summary.status is RunStatus.SUCCESS else 1


def cli(argv: Sequence[str] | None = None) -> int:
    load_dotenv(override=False)
    args = _build_parser().parse_args(argv)
    if args.dry_run and not args.monitor:
        print("Configuration error: --dry-run requires --monitor", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    routes = plan_routes(config)

    if args.monitor:
        try:
            return _run_all_routes(config, routes, dry_run=args.dry_run)
        except StorageError as error:
            print(f"Storage error: {error}", file=sys.stderr)
            return 1

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

"""Command-line entry point for Fly Club."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from flyclub.config import ConfigError, load_config
from flyclub.route_planner import config_fingerprint, plan_routes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub", description="Fly Club flight monitor")
    parser.add_argument("--config", help="Path to an ignored local routes YAML file")
    parser.add_argument(
        "--show-routes",
        action="store_true",
        help="Show configured route endpoints (avoid in shared logs)",
    )
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    routes = plan_routes(config)
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

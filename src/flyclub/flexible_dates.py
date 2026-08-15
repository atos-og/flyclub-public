"""Dedicated lower-frequency monitor for shifted fixed-duration trips."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramError
from flyclub.config import ConfigError, load_config
from flyclub.main import _run_all_routes
from flyclub.route_planner import plan_flexible_date_routes
from flyclub.storage.postgres import StorageError


def _offsets(value: str) -> tuple[int, ...]:
    try:
        offsets = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("offsets must be comma-separated integers") from error
    if not offsets or 0 in offsets or len(set(offsets)) != len(offsets):
        raise argparse.ArgumentTypeError("offsets must be unique, non-zero, and non-empty")
    return offsets


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flyclub-flexible-dates")
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offsets", type=_offsets, default=(-3, -2, -1, 1, 2, 3))
    args = parser.parse_args(argv)
    load_dotenv(override=False)
    try:
        config = load_config(args.config)
        routes = plan_flexible_date_routes(config, offsets=args.offsets)
        return _run_all_routes(
            config,
            routes,
            dry_run=args.dry_run,
            include_health=False,
        )
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
    except StorageError as error:
        print(f"Storage error: {error}", file=sys.stderr)
    except TelegramError as error:
        print(f"Notification error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())

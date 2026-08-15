"""Optional, non-scheduled discovery-market monitor."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramError
from flyclub.config import ConfigError, load_config
from flyclub.main import _run_all_routes
from flyclub.route_planner import plan_discovery_routes
from flyclub.storage.postgres import StorageError


def cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flyclub-discovery")
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_dotenv(override=False)
    try:
        config = load_config(args.config)
        routes = plan_discovery_routes(config)
        if not routes:
            print("Configuration error: no discovery routes are configured", file=sys.stderr)
            return 2
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

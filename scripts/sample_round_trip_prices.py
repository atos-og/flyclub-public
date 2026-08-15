"""Compare outbound and return journey prices without persistence.

This diagnostic intentionally loads an ignored/private route configuration and prints route
details locally. Do not redirect its output into a tracked file.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from dotenv import load_dotenv
from fli.search import SearchFlights

from flyclub.config import load_config
from flyclub.providers.google_flights import GoogleFlightsProvider
from flyclub.route_planner import plan_routes


def _price(value: object) -> Decimal | None:
    return GoogleFlightsProvider._decimal_price(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.queries < 1:
        parser.error("--queries must be at least 1")

    load_dotenv(override=False)
    config = load_config(args.config)
    routes = plan_routes(config)
    provider = GoogleFlightsProvider(retry_attempts=1)
    client = SearchFlights()

    comparisons: list[Decimal] = []
    divergent = 0
    completed = 0
    for query_index in range(args.queries):
        route = routes[query_index % len(routes)]
        raw_results = client.search(
            provider._build_filters(route),
            top_n=config.monitor.max_results_per_route,
            currency=route.currency,
            language="pt-BR",
            country="BR",
        )
        completed += 1
        for option_index, result in enumerate(raw_results or (), start=1):
            journeys = result if isinstance(result, tuple) else (result,)
            outbound = _price(getattr(journeys[0], "price", None))
            final = _price(getattr(journeys[-1], "price", None))
            if outbound is None or final is None:
                print(
                    f"query={completed:02d} option={option_index} "
                    f"outbound={outbound} final={final} comparable=no"
                )
                continue
            difference = abs(outbound - final) / outbound * Decimal("100")
            comparisons.append(difference)
            if difference > 0:
                divergent += 1
            print(
                f"query={completed:02d} option={option_index} "
                f"outbound={outbound} final={final} difference_percent={difference:.4f}"
            )

    average = sum(comparisons, Decimal("0")) / len(comparisons) if comparisons else None
    maximum = max(comparisons) if comparisons else None
    print("SUMMARY")
    print(f"queries={completed}")
    print(f"comparable_options={len(comparisons)}")
    print(f"divergent_options={divergent}")
    print(f"average_difference_percent={average}")
    print(f"maximum_difference_percent={maximum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

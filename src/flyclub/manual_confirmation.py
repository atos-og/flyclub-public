"""Non-persistent, on-demand confirmation for exactly two passengers."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import date

from dotenv import load_dotenv

from flyclub.alerts.formatter import format_manual_confirmation_message
from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.models import (
    CabinClass,
    MaxStops,
    OriginRole,
    RouteDefinition,
    SearchStatus,
)
from flyclub.providers.google_flights import GoogleFlightsProvider

_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")


def _iata(value: str) -> str:
    normalized = value.strip().upper()
    if not _IATA_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError("must be a three-letter IATA code")
    return normalized


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must use YYYY-MM-DD") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub-confirm-two")
    parser.add_argument("--origin", required=True, type=_iata)
    parser.add_argument("--destination", required=True, type=_iata)
    parser.add_argument("--departure-date", required=True, type=_date)
    parser.add_argument("--return-date", required=True, type=_date)
    return parser


def _route(args: argparse.Namespace) -> RouteDefinition:
    if args.return_date <= args.departure_date:
        raise ValueError("return date must be after departure date")
    return RouteDefinition(
        key="manual-two-passengers",
        origin_group="manual_confirmation",
        origin_label=args.origin,
        origin_role=OriginRole.HOME,
        origin_airports=(args.origin,),
        positioning_notice=None,
        destination=args.destination,
        destination_name=None,
        departure_date=args.departure_date,
        return_date=args.return_date,
        passengers=2,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ANY,
        alert_price=None,
    )


def cli(argv: Sequence[str] | None = None) -> int:
    load_dotenv(override=False)
    args = _parser().parse_args(argv)
    try:
        route = _route(args)
    except ValueError as error:
        print(f"Confirmation error: {error}", file=sys.stderr)
        return 2

    outcome = GoogleFlightsProvider().search(route, max_results=5)
    if outcome.status is not SearchStatus.SUCCESS:
        print(f"Confirmation search ended with status: {outcome.status.value}", file=sys.stderr)
        return 1

    message = format_manual_confirmation_message(route=route, option=outcome.options[0])
    try:
        TelegramClient.from_env().send_message(message)
    except TelegramError as error:
        print(f"Notification error: {error}", file=sys.stderr)
        return 1
    print("Two-passenger confirmation sent to Telegram; no history was persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

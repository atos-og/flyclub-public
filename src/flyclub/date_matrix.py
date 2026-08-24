"""Manual independent-date comparison without persistence or alert-policy changes."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.models import (
    CabinClass,
    FlightOption,
    MaxStops,
    OriginRole,
    RouteDefinition,
    SearchStatus,
)
from flyclub.providers.base import FlightProvider
from flyclub.providers.google_flights import GoogleFlightsProvider

_IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
_MAX_WINDOW_DAYS = 3


@dataclass(frozen=True, slots=True)
class DateCandidate:
    """The cheapest normalized itinerary found for one date combination."""

    route: RouteDefinition
    option: FlightOption
    departure_shift_days: int
    return_shift_days: int


@dataclass(frozen=True, slots=True)
class DateMatrixResult:
    """Aggregate result of one sequential, non-persistent matrix search."""

    attempted: int
    candidates: tuple[DateCandidate, ...]
    empty: int
    failed: int


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


def _passengers(value: str) -> int:
    try:
        passengers = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 9") from error
    if not 1 <= passengers <= 9:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 9")
    return passengers


def _window_days(value: str) -> int:
    try:
        window = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 3") from error
    if not 1 <= window <= _MAX_WINDOW_DAYS:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 3")
    return window


def _max_stops(value: str) -> MaxStops:
    try:
        return MaxStops(value.strip().upper())
    except ValueError as error:
        choices = ", ".join(item.value for item in MaxStops)
        raise argparse.ArgumentTypeError(f"must be one of: {choices}") from error


def build_base_route(
    *,
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date,
    passengers: int,
    max_stops: MaxStops,
) -> RouteDefinition:
    """Build one explicit manual route after validating its comparable fields."""

    if return_date <= departure_date:
        raise ValueError("return date must be after departure date")
    if not 1 <= passengers <= 9:
        raise ValueError("passengers must be between 1 and 9")
    return RouteDefinition(
        key="manual-date-matrix-base",
        origin_group="manual_date_matrix",
        origin_label=origin,
        origin_role=OriginRole.HOME,
        origin_airports=(origin,),
        positioning_notice=None,
        destination=destination,
        destination_name=None,
        departure_date=departure_date,
        return_date=return_date,
        passengers=passengers,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=max_stops,
        alert_price=None,
    )


def date_matrix_routes(
    base_route: RouteDefinition,
    *,
    window_days: int,
) -> tuple[tuple[RouteDefinition, int, int], ...]:
    """Create every valid independent departure/return combination in the bounded window."""

    if not 1 <= window_days <= _MAX_WINDOW_DAYS:
        raise ValueError("window days must be between 1 and 3")
    routes: list[tuple[RouteDefinition, int, int]] = []
    for departure_shift in range(-window_days, window_days + 1):
        for return_shift in range(-window_days, window_days + 1):
            departure = base_route.departure_date + timedelta(days=departure_shift)
            returning = base_route.return_date + timedelta(days=return_shift)
            if returning <= departure:
                continue
            routes.append(
                (
                    replace(
                        base_route,
                        key=f"manual-date-matrix-{departure.isoformat()}-{returning.isoformat()}",
                        departure_date=departure,
                        return_date=returning,
                    ),
                    departure_shift,
                    return_shift,
                )
            )
    return tuple(routes)


def scan_date_matrix(
    provider: FlightProvider,
    base_route: RouteDefinition,
    *,
    window_days: int,
) -> DateMatrixResult:
    """Search the complete bounded matrix sequentially and retain one option per combination."""

    planned = date_matrix_routes(base_route, window_days=window_days)
    candidates: list[DateCandidate] = []
    empty = 0
    failed = 0
    for route, departure_shift, return_shift in planned:
        outcome = provider.search(route, max_results=1)
        if outcome.status is SearchStatus.SUCCESS:
            candidates.append(
                DateCandidate(
                    route=route,
                    option=outcome.options[0],
                    departure_shift_days=departure_shift,
                    return_shift_days=return_shift,
                )
            )
        elif outcome.status is SearchStatus.EMPTY:
            empty += 1
        else:
            failed += 1
    return DateMatrixResult(
        attempted=len(planned),
        candidates=tuple(candidates),
        empty=empty,
        failed=failed,
    )


def rank_date_candidates(candidates: Sequence[DateCandidate]) -> tuple[DateCandidate, ...]:
    """Rank by fare, itinerary quality, and smallest deviation from the requested dates."""

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.option.price,
                candidate.option.stops if candidate.option.stops is not None else 999,
                candidate.option.duration_minutes
                if candidate.option.duration_minutes is not None
                else 999_999,
                abs(candidate.departure_shift_days) + abs(candidate.return_shift_days),
                candidate.route.departure_date,
                candidate.route.return_date,
            ),
        )
    )


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {rendered}"
    return f"{currency} {value:.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1')):.1f}".replace(".", ",") + "%"


def _passenger_label(passengers: int) -> str:
    noun = "passageiro" if passengers == 1 else "passageiros"
    return f"{passengers} {noun}"


def _shift_text(label: str, days: int) -> str:
    if days == 0:
        return f"{label} na data desejada"
    direction = "antes" if days < 0 else "depois"
    noun = "dia" if abs(days) == 1 else "dias"
    return f"{label} {abs(days)} {noun} {direction}"


def _itinerary_text(option: FlightOption) -> str:
    airlines = tuple(dict.fromkeys(leg.airline for leg in option.legs if leg.airline))
    airline = " + ".join(airlines) if airlines else "companhia não informada"
    if option.stops is None:
        stops = "escalas não informadas"
    elif option.stops == 0:
        stops = "direto"
    elif option.stops == 1:
        stops = "1 escala"
    else:
        stops = f"{option.stops} escalas"
    if option.duration_minutes is None:
        return f"{airline} · {stops}"
    hours, minutes = divmod(option.duration_minutes, 60)
    return f"{airline} · {stops} · {hours}h{minutes:02d} total"


def _reference_candidate(
    candidates: Sequence[DateCandidate],
) -> DateCandidate | None:
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.departure_shift_days == 0 and candidate.return_shift_days == 0
        ),
        None,
    )


def _comparison_text(candidate: DateCandidate, reference: DateCandidate | None) -> str:
    if reference is None:
        return "Datas desejadas sem preço disponível nesta consulta."
    difference = reference.option.price - candidate.option.price
    if difference == 0:
        return "Mesmo preço das datas desejadas."
    percentage = abs(difference) * Decimal(100) / reference.option.price
    if difference > 0:
        return (
            f"Economiza {_money(difference, candidate.option.currency)} "
            f"({_percent(percentage)}) vs. datas desejadas."
        )
    return (
        f"Custa {_money(abs(difference), candidate.option.currency)} "
        f"({_percent(percentage)}) a mais que as datas desejadas."
    )


def format_date_matrix_message(
    *,
    base_route: RouteDefinition,
    result: DateMatrixResult,
    limit: int = 3,
) -> str:
    """Explain the best date combinations with only observed, normalized information."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    ranked = rank_date_candidates(result.candidates)
    if not ranked:
        raise ValueError("at least one priced date candidate is required")
    selected = ranked[:limit]
    reference = _reference_candidate(ranked)
    lines = [
        f"🗓️ COMPARADOR DE DATAS · TOP {len(selected)}",
        "",
        f"✈️ {base_route.origin_airports[0]} → {base_route.destination}",
        f"Datas desejadas: {base_route.departure_date:%d/%m} a "
        f"{base_route.return_date:%d/%m} · {_passenger_label(base_route.passengers)}",
        f"{result.attempted} combinações consultadas · {len(ranked)} com preço",
    ]
    for index, candidate in enumerate(selected, start=1):
        lines.extend(
            [
                "",
                f"{index}. {candidate.route.departure_date:%d/%m} a "
                f"{candidate.route.return_date:%d/%m}",
                f"💰 {_money(candidate.option.price, candidate.option.currency)} total",
                _comparison_text(candidate, reference),
                f"Mudança: {_shift_text('ida', candidate.departure_shift_days)} · "
                f"{_shift_text('volta', candidate.return_shift_days)}",
                _itinerary_text(candidate.option),
            ]
        )
        url = candidate.option.booking_url or candidate.option.google_flights_url
        if url:
            lines.append(f"🔗 {url}")
    if result.empty or result.failed:
        lines.extend(
            [
                "",
                f"Sem preço: {result.empty} · falhas do provedor: {result.failed}",
            ]
        )
    lines.extend(
        [
            "",
            "Ranking pontual pelo menor preço; desempate por escalas, duração e menor mudança.",
            "Não altera histórico, Deal Score ou alertas automáticos.",
        ]
    )
    message = "\n".join(lines)
    if len(message) > 4096:
        without_links = [line for line in lines if not line.startswith("🔗 ")]
        message = "\n".join(without_links)
    if len(message) > 4096:
        raise ValueError("date comparison message exceeds Telegram's limit")
    return message


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub-date-matrix")
    parser.add_argument("--origin", required=True, type=_iata)
    parser.add_argument("--destination", required=True, type=_iata)
    parser.add_argument("--departure-date", required=True, type=_date)
    parser.add_argument("--return-date", required=True, type=_date)
    parser.add_argument("--window-days", type=_window_days, default=3)
    parser.add_argument("--passengers", type=_passengers, default=1)
    parser.add_argument("--max-stops", type=_max_stops, default=MaxStops.ANY)
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    load_dotenv(override=False)
    args = _parser().parse_args(argv)
    try:
        route = build_base_route(
            origin=args.origin,
            destination=args.destination,
            departure_date=args.departure_date,
            return_date=args.return_date,
            passengers=args.passengers,
            max_stops=args.max_stops,
        )
    except ValueError as error:
        print(f"Date comparison error: {error}", file=sys.stderr)
        return 2

    result = scan_date_matrix(
        GoogleFlightsProvider(),
        route,
        window_days=args.window_days,
    )
    if not result.candidates:
        print(
            "Date comparison found no priced combinations; "
            f"empty={result.empty}, failed={result.failed}.",
            file=sys.stderr,
        )
        return 1
    message = format_date_matrix_message(base_route=route, result=result)
    try:
        TelegramClient.from_env().send_message(message)
    except TelegramError as error:
        print(f"Notification error: {error}", file=sys.stderr)
        return 1
    print(
        "Date comparison sent to Telegram; "
        f"attempted={result.attempted}, priced={len(result.candidates)}, "
        f"empty={result.empty}, failed={result.failed}; no history was persisted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

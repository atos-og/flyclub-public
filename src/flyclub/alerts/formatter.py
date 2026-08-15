"""Short plain-text Telegram messages built only from normalized Fly Club data."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from flyclub.alerts.engine import AlertReason, AlertResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel
from flyclub.models import FlightOption, OriginPriceComparison, RouteDefinition, RouteKind

MANUAL_CONFIRMATION_WORKFLOW_URL = (
    "https://github.com/atos-og/flyclub/actions/workflows/confirm-two-passengers.yml"
)


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {rendered}"
    return f"{currency} {value:.2f}"


def _title(route: RouteDefinition, evaluation: RoutePriceEvaluation) -> str:
    score = evaluation.deal_score.score
    if route.kind is RouteKind.FLEXIBLE:
        prefix = "🗓️ DATA FLEXÍVEL"
    elif route.kind is RouteKind.DISCOVERY:
        prefix = "🔎 DESCOBERTA"
    else:
        prefix = "🔥 OPORTUNIDADE"
    if score is None:
        return prefix
    if score >= 90:
        return f"{prefix} EXCEPCIONAL · {score}/100"
    return f"{prefix} · {score}/100"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1')):.1f}".replace(".", ",") + "%"


def _passenger_label(passengers: int) -> str:
    noun = "passageiro" if passengers == 1 else "passageiros"
    return f"{passengers} {noun}"


def _confidence_label(confidence: ConfidenceLevel) -> str:
    labels = {
        ConfidenceLevel.INSUFFICIENT: "insuficiente",
        ConfidenceLevel.LOW: "baixa (provisória)",
        ConfidenceLevel.MODERATE: "moderada",
        ConfidenceLevel.HIGH: "alta",
    }
    return labels[confidence]


def _history_summary(
    confidence: ConfidenceLevel,
    sample_size: int,
    percentile_rank: Decimal | None,
) -> str:
    if confidence is ConfidenceLevel.INSUFFICIENT or percentile_rank is None:
        return f"📊 Histórico inicial: {sample_size} observações"
    lowest_percent = max(
        1,
        min(100, int(percentile_rank.to_integral_value(rounding=ROUND_CEILING))),
    )
    return (
        f"📊 Entre os {lowest_percent}% menores preços de {sample_size} observações "
        f"· confiança {_confidence_label(confidence)}"
    )


def format_alert_message(
    *,
    route: RouteDefinition,
    option: FlightOption,
    evaluation: RoutePriceEvaluation,
    alert: AlertResult,
    origin_comparison: OriginPriceComparison | None = None,
) -> str:
    """Format one consolidated alert without inventing itinerary or URL data."""

    actual_origin = (
        option.legs[0].origin_airport if option.legs else "/".join(route.origin_airports)
    )
    destination = route.destination_name or route.destination
    airlines = tuple(dict.fromkeys(leg.airline for leg in option.legs if leg.airline))
    airline_text = " + ".join(airlines) if airlines else "Companhia não informada"
    if option.stops is None:
        stops_text = "escalas não informadas"
    elif option.stops == 0:
        stops_text = "direto"
    elif option.stops == 1:
        stops_text = "1 escala"
    else:
        stops_text = f"{option.stops} escalas"

    lines = [
        _title(route, evaluation),
        "",
        f"✈️ {actual_origin} → {destination}",
        f"📅 {route.departure_date:%d/%m} a {route.return_date:%d/%m} "
        f"· {airline_text} · {stops_text}",
        "",
        f"💰 {_money(option.price, option.currency)} total · {_passenger_label(route.passengers)}",
    ]

    if (
        alert.drop_amount is not None
        and alert.drop_amount > 0
        and alert.drop_percent is not None
        and alert.drop_percent > 0
    ):
        lines.append(
            f"↓ {_money(alert.drop_amount, option.currency)} ({_percent(alert.drop_percent)}) "
            "desde o último alerta"
        )
    statistics = evaluation.statistics
    if statistics.p50 is not None and option.price < statistics.p50:
        savings = statistics.p50 - option.price
        discount = savings * Decimal(100) / statistics.p50
        lines.append(
            f"↓ {_money(savings, option.currency)} ({_percent(discount)}) "
            f"abaixo do preço típico de {_money(statistics.p50, option.currency)}"
        )

    lines.extend(
        [
            "",
            _history_summary(
                statistics.confidence,
                statistics.sample_size,
                statistics.percentile_rank,
            ),
        ]
    )
    if statistics.recorded_low is not None:
        recorded_low = _money(statistics.recorded_low, option.currency)
        lines.append(f"🏆 Menor já registrado: {recorded_low}")

    reason_labels = {
        AlertReason.PRICE_TARGET: "teto de preço atingido",
        AlertReason.NEW_LOW: "novo menor preço registrado",
        AlertReason.EXCEPTIONAL_DEAL: "preço estatisticamente excepcional",
        AlertReason.SIGNIFICANT_DROP: "nova queda significativa",
    }
    visible_reasons = [reason_labels[reason] for reason in alert.reasons if reason in reason_labels]
    if visible_reasons:
        lines.append("🔔 Motivos: " + "; ".join(visible_reasons))

    if (
        evaluation.deal_score.score is not None
        and evaluation.deal_score.score >= 80
        and (statistics.confidence in {ConfidenceLevel.MODERATE, ConfidenceLevel.HIGH})
    ):
        lines.extend(
            [
                "",
                "👥 Antes de comprar, confirme o preço para 2 passageiros:",
                MANUAL_CONFIRMATION_WORKFLOW_URL,
            ]
        )

    comparison_shown = False
    if origin_comparison is not None and option.price < origin_comparison.reference_price:
        savings = origin_comparison.reference_price - option.price
        comparison_shown = True
        lines.extend(
            [
                "",
                f"📍 Sair de {actual_origin} está {_money(savings, option.currency)} mais barato "
                f"que sair de {origin_comparison.reference_origin} hoje.",
                f"O deslocamento até {route.origin_label} não está incluído; só compensa se "
                f"custar menos que {_money(savings, option.currency)}.",
            ]
        )
    if route.positioning_notice and not comparison_shown:
        lines.extend(["", f"⚠️ {route.positioning_notice}"])
    url = option.booking_url or option.google_flights_url
    if url:
        lines.extend(["", f"🔗 Ver oferta: {url}"])
    return "\n".join(lines)


def format_manual_confirmation_message(*, route: RouteDefinition, option: FlightOption) -> str:
    """Format a non-persistent two-passenger spot check for Telegram."""

    actual_origin = (
        option.legs[0].origin_airport if option.legs else "/".join(route.origin_airports)
    )
    airlines = tuple(dict.fromkeys(leg.airline for leg in option.legs if leg.airline))
    airline_text = " + ".join(airlines) if airlines else "Companhia não informada"
    if option.stops is None:
        stops_text = "escalas não informadas"
    elif option.stops == 0:
        stops_text = "direto"
    elif option.stops == 1:
        stops_text = "1 escala"
    else:
        stops_text = f"{option.stops} escalas"
    per_passenger = option.price / Decimal(route.passengers)
    lines = [
        "👥 CONFIRMAÇÃO MANUAL · 2 PASSAGEIROS",
        "",
        f"✈️ {actual_origin} → {route.destination}",
        f"📅 {route.departure_date:%d/%m} a {route.return_date:%d/%m} "
        f"· {airline_text} · {stops_text}",
        "",
        f"💰 {_money(option.price, option.currency)} total · 2 passageiros",
        f"Por pessoa: {_money(per_passenger, option.currency)}",
        "",
        "Consulta pontual: não altera o histórico nem dispara o Deal Score.",
    ]
    url = option.booking_url or option.google_flights_url
    if url:
        lines.extend(["", f"🔗 Ver oferta: {url}"])
    return "\n".join(lines)

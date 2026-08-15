"""Short plain-text Telegram messages built only from normalized Fly Club data."""

from __future__ import annotations

from decimal import Decimal

from flyclub.alerts.engine import AlertReason, AlertResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel
from flyclub.models import FlightOption, OriginPriceComparison, RouteDefinition


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {rendered}"
    return f"{currency} {value:.2f}"


def _title(evaluation: RoutePriceEvaluation) -> str:
    score = evaluation.deal_score.score
    if score is None:
        return "🔥 OPORTUNIDADE"
    if score >= 90:
        return f"🔥 OPORTUNIDADE EXCEPCIONAL · {score}/100"
    return f"🔥 OPORTUNIDADE · {score}/100"


def _confidence(confidence: ConfidenceLevel, sample_size: int) -> str:
    labels = {
        ConfidenceLevel.INSUFFICIENT: "insuficiente",
        ConfidenceLevel.LOW: "baixa · provisório",
        ConfidenceLevel.MODERATE: "moderada",
        ConfidenceLevel.HIGH: "alta",
    }
    return f"🎯 Confiança: {labels[confidence]} · {sample_size} observações"


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
        _title(evaluation),
        "",
        f"✈️ {actual_origin} → {destination}",
        f"{route.departure_date:%d/%m} → {route.return_date:%d/%m}",
        f"{airline_text} · {stops_text}",
        "",
        _money(option.price, option.currency),
    ]

    if alert.drop_percent is not None and alert.drop_percent > 0:
        lines.append(f"↓ {alert.drop_percent.quantize(Decimal('0.1'))}% desde o último alerta")
    statistics = evaluation.statistics
    if statistics.p50 is not None and option.price < statistics.p50:
        discount = (statistics.p50 - option.price) * Decimal(100) / statistics.p50
        lines.append(f"↓ {discount.quantize(Decimal('0.1'))}% vs. mediana histórica")

    if statistics.p10 is not None and statistics.p50 is not None:
        lines.extend(
            [
                "",
                f"P10: {_money(statistics.p10, option.currency)}",
                f"P50: {_money(statistics.p50, option.currency)}",
            ]
        )
    if statistics.recorded_low is not None:
        recorded_low = _money(statistics.recorded_low, option.currency)
        lines.append(f"🏆 Menor registrado no monitoramento: {recorded_low}")
    if statistics.percentile_rank is not None:
        lines.append(f"📊 Percentil atual: P{statistics.percentile_rank.quantize(Decimal('1'))}")
    lines.append(_confidence(statistics.confidence, statistics.sample_size))

    reason_labels = {
        AlertReason.PRICE_TARGET: "teto de preço atingido",
        AlertReason.NEW_LOW: "novo menor preço registrado",
        AlertReason.EXCEPTIONAL_DEAL: "preço estatisticamente excepcional",
        AlertReason.SIGNIFICANT_DROP: "nova queda significativa",
    }
    visible_reasons = [reason_labels[reason] for reason in alert.reasons if reason in reason_labels]
    if visible_reasons:
        lines.extend(["", "Motivos: " + "; ".join(visible_reasons)])

    if origin_comparison is not None and option.price < origin_comparison.reference_price:
        savings = origin_comparison.reference_price - option.price
        lines.extend(
            [
                "",
                f"💰 {_money(savings, option.currency)} abaixo da melhor opção atual "
                f"saindo de {origin_comparison.reference_origin}.",
            ]
        )
    if route.positioning_notice:
        lines.extend(["", f"⚠️ {route.positioning_notice}"])
    url = option.booking_url or option.google_flights_url
    if url:
        lines.extend(["", f"🔗 Abrir oferta: {url}"])
    return "\n".join(lines)

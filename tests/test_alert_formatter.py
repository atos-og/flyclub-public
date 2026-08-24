from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from flyclub.alerts.engine import AlertDecision, AlertReason, AlertResult
from flyclub.alerts.formatter import (
    MANUAL_CONFIRMATION_WORKFLOW_URL,
    format_alert_message,
    format_manual_confirmation_message,
)
from flyclub.analysis.deal_score import DealClassification, DealScoreResult
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel, PriceStatistics
from flyclub.analysis.trend import TrendAnalysis, TrendDirection
from flyclub.models import (
    CabinClass,
    FlightLeg,
    FlightOption,
    MaxStops,
    OriginPriceComparison,
    OriginRole,
    RouteDefinition,
    RouteKind,
)


def _route(*, positioning: bool = False, passengers: int = 2) -> RouteDefinition:
    return RouteDefinition(
        key="example",
        origin_group="from_sp" if positioning else "from_bh",
        origin_label="São Paulo" if positioning else "Belo Horizonte",
        origin_role=OriginRole.POSITIONING if positioning else OriginRole.HOME,
        origin_airports=("GRU", "VCP", "CGH") if positioning else ("CNF",),
        positioning_notice=(
            "Saída de São Paulo — deslocamento BH → SP não incluído." if positioning else None
        ),
        destination="LIS",
        destination_name="Lisboa",
        departure_date=date(2027, 7, 1),
        return_date=date(2027, 7, 8),
        passengers=passengers,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ANY,
        alert_price=None,
        positioning_cost_estimate=Decimal("650") if positioning else None,
    )


def _option(
    *,
    origin: str = "CNF",
    url: str | None = "https://www.google.com/travel/flights/example",
) -> FlightOption:
    return FlightOption(
        price=Decimal("3030"),
        currency="BRL",
        stops=1,
        google_flights_url=url,
        legs=(
            FlightLeg(
                journey_index=0,
                origin_airport=origin,
                destination_airport="LIS",
                departure_time=datetime(2027, 7, 1, tzinfo=UTC),
                arrival_time=None,
                airline="TP",
                flight_number="TP1",
            ),
        ),
    )


def _evaluation() -> RoutePriceEvaluation:
    confidence = ConfidenceLevel.HIGH
    return RoutePriceEvaluation(
        statistics=PriceStatistics(
            sample_size=120,
            confidence=confidence,
            p10=Decimal("3150"),
            p50=Decimal("3760"),
            p90=Decimal("4420"),
            percentile_rank=Decimal("6"),
            recorded_low=Decimal("2980"),
        ),
        trend=TrendAnalysis(
            8, TrendDirection.FALLING, Decimal("-4"), Decimal("3500"), Decimal("3360")
        ),
        recent_drop=None,
        deal_score=DealScoreResult(
            score=94,
            classification=DealClassification.EXCEPTIONAL,
            confidence=confidence,
            provisional=False,
            components=(),
        ),
    )


def _alert() -> AlertResult:
    return AlertResult(
        decision=AlertDecision.SEND,
        reasons=(AlertReason.NEW_LOW, AlertReason.EXCEPTIONAL_DEAL),
        drop_amount=Decimal("250"),
        drop_percent=Decimal("7.62"),
    )


def test_formatter_builds_short_actionable_explainable_message() -> None:
    message = format_alert_message(
        route=_route(), option=_option(), evaluation=_evaluation(), alert=_alert()
    )

    assert (
        message
        == """🔥 OPORTUNIDADE EXCEPCIONAL · 94/100

✈️ CNF → Lisboa
📅 01/07 a 08/07 · TP · 1 escala

💰 R$ 3.030,00 total · 2 passageiros
↓ R$ 250,00 (7,6%) desde o último alerta
↓ R$ 730,00 (19,4%) abaixo do preço típico de R$ 3.760,00

📊 Entre os 6% menores preços de 120 observações · confiança alta
🏆 Menor já registrado: R$ 2.980,00
🔔 Motivos: novo menor preço registrado; preço estatisticamente excepcional

👥 Antes de comprar, confirme o preço para 2 passageiros:
https://github.com/atos-og/flyclub/actions/workflows/confirm-two-passengers.yml

🔗 <a href="https://www.google.com/travel/flights/example">Ver oferta</a>"""
    )
    assert len(message) < 4096


def test_formatter_labels_single_passenger_price() -> None:
    message = format_alert_message(
        route=_route(passengers=1), option=_option(), evaluation=_evaluation(), alert=_alert()
    )

    assert "💰 R$ 3.030,00 total · 1 passageiro" in message


def test_formatter_warns_when_positioning_trip_starts_in_sao_paulo() -> None:
    message = format_alert_message(
        route=_route(positioning=True),
        option=_option(origin="GRU"),
        evaluation=_evaluation(),
        alert=_alert(),
    )

    assert "deslocamento BH → SP não incluído" in message


def test_formatter_contextualizes_material_positioning_savings() -> None:
    message = format_alert_message(
        route=_route(positioning=True),
        option=_option(origin="GRU"),
        evaluation=_evaluation(),
        alert=_alert(),
        origin_comparison=OriginPriceComparison("CNF", Decimal("3724")),
    )

    assert "Economia bruta saindo de GRU: R$ 694,00 vs. CNF" in message
    assert "Custo estimado de posicionamento: R$ 650,00" in message
    assert "Economia líquida estimada: R$ 44,00" in message
    assert "deslocamento BH → SP não incluído" not in message


def test_formatter_does_not_invent_missing_url() -> None:
    message = format_alert_message(
        route=_route(), option=_option(url=None), evaluation=_evaluation(), alert=_alert()
    )

    assert "Ver oferta" not in message


def test_formatter_hides_long_url_and_escapes_html() -> None:
    route = replace(_route(), destination_name="Buenos Aires & região")
    long_url = "https://www.google.com/travel/flights/booking?token=a&curr=BRL"

    message = format_alert_message(
        route=route,
        option=_option(url=long_url),
        evaluation=_evaluation(),
        alert=_alert(),
    )

    assert "Buenos Aires &amp; região" in message
    assert long_url not in message
    assert (
        '<a href="https://www.google.com/travel/flights/booking?token=a&amp;curr=BRL">'
        "Ver oferta</a>"
    ) in message


def test_confirmation_reminder_requires_score_80_and_moderate_confidence() -> None:
    evaluation = _evaluation()
    low_score = RoutePriceEvaluation(
        statistics=evaluation.statistics,
        trend=evaluation.trend,
        recent_drop=evaluation.recent_drop,
        deal_score=DealScoreResult(
            score=79,
            classification=DealClassification.GREAT,
            confidence=ConfidenceLevel.HIGH,
            provisional=False,
            components=(),
        ),
    )

    message = format_alert_message(
        route=_route(), option=_option(), evaluation=low_score, alert=_alert()
    )

    assert MANUAL_CONFIRMATION_WORKFLOW_URL not in message


def test_manual_confirmation_is_clearly_tagged_and_scoped_to_two_passengers() -> None:
    message = format_manual_confirmation_message(route=_route(), option=_option())

    assert message.startswith("👥 CONFIRMAÇÃO MANUAL · 2 PASSAGEIROS")
    assert "R$ 3.030,00 total · 2 passageiros" in message
    assert "Por pessoa: R$ 1.515,00" in message
    assert "não altera o histórico nem dispara o Deal Score" in message


def test_flexible_date_alert_is_visually_distinct() -> None:
    flexible = replace(_route(), kind=RouteKind.FLEXIBLE)

    message = format_alert_message(
        route=flexible, option=_option(), evaluation=_evaluation(), alert=_alert()
    )

    assert message.startswith("🗓️ DATA FLEXÍVEL EXCEPCIONAL")


def test_discovery_alert_is_visually_distinct() -> None:
    discovery = replace(_route(), kind=RouteKind.DISCOVERY)

    message = format_alert_message(
        route=discovery, option=_option(), evaluation=_evaluation(), alert=_alert()
    )

    assert message.startswith("🔎 DESCOBERTA EXCEPCIONAL")

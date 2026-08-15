from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from flyclub.alerts.engine import AlertDecision, AlertReason, AlertResult
from flyclub.alerts.formatter import format_alert_message
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
)


def _route(*, positioning: bool = False) -> RouteDefinition:
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
        passengers=2,
        cabin=CabinClass.ECONOMY,
        currency="BRL",
        max_stops=MaxStops.ANY,
        alert_price=None,
    )


def _option(*, url: str | None = "https://www.google.com/travel/flights/example") -> FlightOption:
    return FlightOption(
        price=Decimal("3030"),
        currency="BRL",
        stops=1,
        google_flights_url=url,
        legs=(
            FlightLeg(
                journey_index=0,
                origin_airport="CNF",
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

    assert "OPORTUNIDADE EXCEPCIONAL · 94/100" in message
    assert "CNF → Lisboa" in message
    assert "R$ 3.030,00" in message
    assert "P10: R$ 3.150,00" in message
    assert "Percentil atual: P6" in message
    assert "Confiança: alta · 120 observações" in message
    assert "https://www.google.com/travel/flights/example" in message
    assert len(message) < 4096


def test_formatter_warns_when_positioning_trip_starts_in_sao_paulo() -> None:
    message = format_alert_message(
        route=_route(positioning=True), option=_option(), evaluation=_evaluation(), alert=_alert()
    )

    assert "deslocamento BH → SP não incluído" in message


def test_formatter_contextualizes_material_positioning_savings() -> None:
    message = format_alert_message(
        route=_route(positioning=True),
        option=_option(),
        evaluation=_evaluation(),
        alert=_alert(),
        origin_comparison=OriginPriceComparison("CNF", Decimal("3724")),
    )

    assert "R$ 694,00 abaixo da melhor opção atual saindo de CNF" in message
    assert "deslocamento BH → SP não incluído" in message


def test_formatter_does_not_invent_missing_url() -> None:
    message = format_alert_message(
        route=_route(), option=_option(url=None), evaluation=_evaluation(), alert=_alert()
    )

    assert "Abrir oferta" not in message

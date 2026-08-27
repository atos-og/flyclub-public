"""Strict alert policy and compact Telegram delivery for flexible markets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from html import escape

from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.analysis.evaluator import RoutePriceEvaluation
from flyclub.analysis.statistics import ConfidenceLevel
from flyclub.flexible_market_models import (
    CalendarFare,
    FlexibleMarketDefinition,
    FlexibleMarketPeriod,
)
from flyclub.models import FlightOption
from flyclub.storage.flexible_market import (
    FlexibleDecision,
    FlexibleMarketRepository,
    LastFlexibleAlert,
)


class FlexibleAlertReason(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    BELOW_PERIOD_THRESHOLD = "BELOW_PERIOD_THRESHOLD"
    QUALIFIED_SCORE = "QUALIFIED_SCORE"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    UNCHANGED_OFFER = "UNCHANGED_OFFER"
    SIGNIFICANT_DROP = "SIGNIFICANT_DROP"


@dataclass(frozen=True, slots=True)
class FlexibleAlertPolicy:
    min_score_samples: int = 12
    cooldown_hours: int = 24
    resend_min_drop_amount: Decimal = Decimal("100")
    resend_min_drop_percent: Decimal = Decimal("5")


@dataclass(frozen=True, slots=True)
class FlexibleAlertResult:
    decision: FlexibleDecision
    reasons: tuple[FlexibleAlertReason, ...]
    drop_amount: Decimal | None = None
    drop_percent: Decimal | None = None


def decide_flexible_alert(
    *,
    current_price: Decimal,
    current_at: datetime,
    departure_date: object,
    arrival_airport: str,
    evaluation: RoutePriceEvaluation,
    minimum_deal_score: int,
    last_alert: LastFlexibleAlert | None,
    policy: FlexibleAlertPolicy,
) -> FlexibleAlertResult:
    score = evaluation.deal_score.score
    if evaluation.statistics.sample_size < policy.min_score_samples or score is None:
        return FlexibleAlertResult(
            FlexibleDecision.SUPPRESS,
            (FlexibleAlertReason.INSUFFICIENT_HISTORY,),
        )
    if score < minimum_deal_score:
        return FlexibleAlertResult(
            FlexibleDecision.SUPPRESS,
            (FlexibleAlertReason.BELOW_PERIOD_THRESHOLD,),
        )
    if last_alert is None:
        return FlexibleAlertResult(
            FlexibleDecision.SEND,
            (FlexibleAlertReason.QUALIFIED_SCORE,),
        )

    drop_amount = last_alert.price - current_price
    drop_percent = drop_amount * Decimal(100) / last_alert.price
    significant_drop = (
        drop_amount >= policy.resend_min_drop_amount
        and drop_percent >= policy.resend_min_drop_percent
    )
    reasons = [FlexibleAlertReason.QUALIFIED_SCORE]
    if significant_drop:
        reasons.append(FlexibleAlertReason.SIGNIFICANT_DROP)
        return FlexibleAlertResult(
            FlexibleDecision.SEND,
            tuple(reasons),
            drop_amount=drop_amount,
            drop_percent=drop_percent,
        )

    if current_at - last_alert.observed_at < timedelta(hours=policy.cooldown_hours):
        reasons.append(FlexibleAlertReason.COOLDOWN_ACTIVE)
        return FlexibleAlertResult(
            FlexibleDecision.SUPPRESS,
            tuple(reasons),
            drop_amount=drop_amount,
            drop_percent=drop_percent,
        )
    if (
        departure_date == last_alert.departure_date
        and arrival_airport == last_alert.arrival_airport
        and current_price >= last_alert.price
    ):
        reasons.append(FlexibleAlertReason.UNCHANGED_OFFER)
        return FlexibleAlertResult(
            FlexibleDecision.SUPPRESS,
            tuple(reasons),
            drop_amount=drop_amount,
            drop_percent=drop_percent,
        )
    return FlexibleAlertResult(
        FlexibleDecision.SEND,
        tuple(reasons),
        drop_amount=drop_amount,
        drop_percent=drop_percent,
    )


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {rendered}"
    return f"{currency} {value:.2f}"


def _confidence(confidence: ConfidenceLevel) -> str:
    return {
        ConfidenceLevel.INSUFFICIENT: "insuficiente",
        ConfidenceLevel.LOW: "baixa (provisória)",
        ConfidenceLevel.MODERATE: "moderada",
        ConfidenceLevel.HIGH: "alta",
    }[confidence]


def format_flexible_market_alert(
    *,
    market: FlexibleMarketDefinition,
    period: FlexibleMarketPeriod,
    fare: CalendarFare,
    option: FlightOption,
    evaluation: RoutePriceEvaluation,
    result: FlexibleAlertResult,
) -> str:
    score = evaluation.deal_score.score
    prefix = "🗓️ GARIMPO FLEXÍVEL"
    if score is not None and score >= 90:
        prefix += " EXCEPCIONAL"
    title = prefix if score is None else f"{prefix} · {score}/100"
    outbound = [leg for leg in option.legs if leg.journey_index == 0]
    actual_origin = outbound[0].origin_airport if outbound else "/".join(market.origin_airports)
    actual_destination = (
        outbound[-1].destination_airport if outbound else "/".join(market.destination_airports)
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
    statistics = evaluation.statistics
    lines = [
        title,
        "",
        f"✈️ {actual_origin} → {actual_destination} · {market.label}",
        f"📅 {fare.departure_date:%d/%m/%Y} a {fare.return_date:%d/%m/%Y} "
        f"· {market.trip_duration_days} dias",
        f"{airline_text} · {stops_text}",
        "",
        f"💰 {_money(option.price, option.currency)} total · {market.passengers} passageiro",
    ]
    if statistics.p50 is not None and option.price < statistics.p50:
        savings = statistics.p50 - option.price
        percent = savings * Decimal(100) / statistics.p50
        rendered_percent = f"{percent.quantize(Decimal('0.1')):.1f}".replace(".", ",")
        lines.append(
            f"↓ {_money(savings, option.currency)} ({rendered_percent}%) abaixo do preço típico"
        )
    if result.drop_amount is not None and result.drop_amount > 0 and result.drop_percent:
        rendered_drop = f"{result.drop_percent.quantize(Decimal('0.1')):.1f}".replace(".", ",")
        lines.append(
            f"↓ {_money(result.drop_amount, option.currency)} ({rendered_drop}%) "
            "desde o último alerta flexível"
        )
    if statistics.percentile_rank is not None:
        rank = max(
            1,
            min(
                100,
                int(statistics.percentile_rank.to_integral_value(rounding=ROUND_CEILING)),
            ),
        )
        lines.extend(
            [
                "",
                f"📊 Entre os {rank}% menores preços de {statistics.sample_size} observações "
                f"· confiança {_confidence(statistics.confidence)}",
            ]
        )
    lines.extend(
        [
            f"🎯 Corte deste período: {period.minimum_deal_score}/100",
            "✅ Datas garimpadas e tarifa confirmada antes do alerta",
        ]
    )
    message = escape("\n".join(lines))
    url = option.booking_url or option.google_flights_url
    if url:
        message += f'\n\n🔗 <a href="{escape(url, quote=True)}">Ver oferta</a>'
    return message


class FlexibleMarketAlertCoordinator:
    def __init__(
        self,
        repository: FlexibleMarketRepository,
        telegram: TelegramClient,
        policy: FlexibleAlertPolicy,
    ) -> None:
        self._repository = repository
        self._telegram = telegram
        self._policy = policy

    def handle(
        self,
        *,
        check_id: object,
        market: FlexibleMarketDefinition,
        period: FlexibleMarketPeriod,
        fare: CalendarFare,
        option: FlightOption,
        current_at: datetime,
        evaluation: RoutePriceEvaluation,
    ) -> bool:
        outbound = [leg for leg in option.legs if leg.journey_index == 0]
        arrival = outbound[-1].destination_airport
        last_alert = self._repository.last_sent_alert(market_key=market.key, period_key=period.key)
        result = decide_flexible_alert(
            current_price=option.price,
            current_at=current_at,
            departure_date=fare.departure_date,
            arrival_airport=arrival,
            evaluation=evaluation,
            minimum_deal_score=period.minimum_deal_score,
            last_alert=last_alert,
            policy=self._policy,
        )
        record = self._repository.record_alert_decision(
            check_id=check_id,
            market_key=market.key,
            period_key=period.key,
            decision=result.decision,
            deal_score=evaluation.deal_score.score,
            reason_codes=tuple(reason.value for reason in result.reasons),
            created_at=current_at,
        )
        if result.decision is FlexibleDecision.SUPPRESS or not record.created:
            return False
        message = format_flexible_market_alert(
            market=market,
            period=period,
            fare=fare,
            option=option,
            evaluation=evaluation,
            result=result,
        )
        try:
            delivery = self._telegram.send_message(message, parse_mode="HTML")
        except TelegramError as error:
            self._repository.mark_alert_failed(
                alert_id=record.alert_id, error_code=type(error).__name__
            )
            raise
        self._repository.mark_alert_sent(
            alert_id=record.alert_id,
            telegram_message_id=delivery.message_id,
        )
        return True

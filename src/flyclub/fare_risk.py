"""Deterministic comparison of explicitly verified fare flexibility rules."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramClient, TelegramError

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_CURRENT_SOURCE_MAX_AGE_DAYS = 7
_BRASILIA = ZoneInfo("America/Sao_Paulo")


class CancellationPolicy(StrEnum):
    FULL_REFUND = "FULL_REFUND"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    NON_REFUNDABLE = "NON_REFUNDABLE"


class ChangePolicy(StrEnum):
    FREE = "FREE"
    WITH_FEE = "WITH_FEE"
    NOT_ALLOWED = "NOT_ALLOWED"


class FareRiskLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class FarePolicyOption:
    """One quoted fare and its user-verified rules from a specific source."""

    label: str
    price: Decimal
    currency: str
    cancellation: CancellationPolicy
    cancellation_penalty: Decimal
    change: ChangePolicy
    change_penalty: Decimal
    fare_difference_applies: bool
    source_url: str
    verified_on: date

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label or len(label) > 80 or any(character in label for character in "\r\n"):
            raise ValueError("fare label must contain 1 to 80 characters on one line")
        if not isinstance(self.price, Decimal):
            raise TypeError("fare price must use Decimal")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("fare price must be finite and greater than zero")
        if not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("currency must be a three-letter ISO 4217 code")
        for name, value in (
            ("cancellation penalty", self.cancellation_penalty),
            ("change penalty", self.change_penalty),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must use Decimal")
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.cancellation is CancellationPolicy.FULL_REFUND and self.cancellation_penalty != 0:
            raise ValueError("a fully refundable fare must have zero cancellation penalty")
        if self.cancellation is CancellationPolicy.PARTIAL_REFUND and not (
            Decimal(0) < self.cancellation_penalty < self.price
        ):
            raise ValueError("a partial refund requires a penalty between zero and the fare price")
        if (
            self.cancellation is CancellationPolicy.NON_REFUNDABLE
            and self.cancellation_penalty != 0
        ):
            raise ValueError("a non-refundable fare must use zero explicit cancellation penalty")
        if self.change is ChangePolicy.FREE and self.change_penalty != 0:
            raise ValueError("a free change must have zero change penalty")
        if self.change is ChangePolicy.WITH_FEE and self.change_penalty <= 0:
            raise ValueError("a paid change requires a positive change penalty")
        if self.change is ChangePolicy.NOT_ALLOWED and self.change_penalty != 0:
            raise ValueError("a non-changeable fare must use zero explicit change penalty")
        parsed = urlparse(self.source_url)
        if (
            self.source_url.strip() != self.source_url
            or any(ord(character) < 32 for character in self.source_url)
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise ValueError("rules source must be a valid HTTP(S) URL")


@dataclass(frozen=True, slots=True)
class FareRiskAssessment:
    option: FarePolicyOption
    cancellation_loss: Decimal
    change_fixed_cost: Decimal
    maximum_fixed_exposure: Decimal
    exposure_ratio: Decimal
    level: FareRiskLevel
    source_age_days: int
    source_current: bool


@dataclass(frozen=True, slots=True)
class FareRiskComparison:
    assessments: tuple[FareRiskAssessment, ...]
    recommendation: FareRiskAssessment | None


def assess_fare_risk(option: FarePolicyOption, *, today: date) -> FareRiskAssessment:
    """Calculate fixed financial exposure without inventing unknown future fare differences."""

    source_age_days = (today - option.verified_on).days
    if source_age_days < 0:
        raise ValueError("rules verification date cannot be in the future")
    if option.cancellation is CancellationPolicy.NON_REFUNDABLE:
        cancellation_loss = option.price
    else:
        cancellation_loss = option.cancellation_penalty
    if option.change is ChangePolicy.NOT_ALLOWED:
        change_fixed_cost = option.price
    else:
        change_fixed_cost = option.change_penalty
    maximum_fixed_exposure = max(cancellation_loss, change_fixed_cost)
    exposure_ratio = maximum_fixed_exposure / option.price
    if exposure_ratio <= Decimal("0.10"):
        level = FareRiskLevel.LOW
    elif exposure_ratio <= Decimal("0.40"):
        level = FareRiskLevel.MODERATE
    else:
        level = FareRiskLevel.HIGH
    return FareRiskAssessment(
        option=option,
        cancellation_loss=cancellation_loss,
        change_fixed_cost=change_fixed_cost,
        maximum_fixed_exposure=maximum_fixed_exposure,
        exposure_ratio=exposure_ratio,
        level=level,
        source_age_days=source_age_days,
        source_current=source_age_days <= _CURRENT_SOURCE_MAX_AGE_DAYS,
    )


def compare_fare_risk(
    options: Sequence[FarePolicyOption],
    *,
    today: date,
) -> FareRiskComparison:
    """Rank complete, current fare rules by fixed exposure, then quoted price."""

    if len(options) < 2:
        raise ValueError("at least two fares are required for comparison")
    currencies = {option.currency for option in options}
    if len(currencies) != 1:
        raise ValueError("all compared fares must use the same currency")
    assessments = tuple(
        sorted(
            (assess_fare_risk(option, today=today) for option in options),
            key=lambda assessment: (
                assessment.maximum_fixed_exposure,
                assessment.exposure_ratio,
                assessment.option.price,
                assessment.option.label.casefold(),
            ),
        )
    )
    recommendation = assessments[0] if all(item.source_current for item in assessments) else None
    return FareRiskComparison(assessments=assessments, recommendation=recommendation)


def _money(value: Decimal, currency: str) -> str:
    if currency == "BRL":
        rendered = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"R$ {rendered}"
    return f"{currency} {value:.2f}"


def _percent(value: Decimal) -> str:
    return f"{(value * Decimal(100)).quantize(Decimal('0.1')):.1f}".replace(".", ",") + "%"


def _cancellation_text(assessment: FareRiskAssessment) -> str:
    policy = assessment.option.cancellation
    if policy is CancellationPolicy.FULL_REFUND:
        return "reembolso integral; perda fixa R$ 0"
    if policy is CancellationPolicy.PARTIAL_REFUND:
        return (
            "reembolso parcial; perda fixa "
            f"{_money(assessment.cancellation_loss, assessment.option.currency)}"
        )
    return (
        "não reembolsável; perda potencial "
        f"{_money(assessment.cancellation_loss, assessment.option.currency)}"
    )


def _change_text(assessment: FareRiskAssessment) -> str:
    option = assessment.option
    if option.change is ChangePolicy.NOT_ALLOWED:
        return "não permitida; pode exigir nova passagem"
    if option.change is ChangePolicy.FREE:
        text = "permitida sem multa"
    else:
        text = f"permitida com multa de {_money(option.change_penalty, option.currency)}"
    if option.fare_difference_applies:
        text += " + eventual diferença tarifária"
    return text


def format_fare_risk_message(comparison: FareRiskComparison) -> str:
    """Build a source-aware Telegram comparison with no generated policy claims."""

    level_labels = {
        FareRiskLevel.LOW: "baixo",
        FareRiskLevel.MODERATE: "moderado",
        FareRiskLevel.HIGH: "alto",
    }
    lines = [
        "🛡️ FLEXIBILIDADE TARIFÁRIA",
        "",
        "Ranking por menor exposição financeira fixa; preço desempata.",
    ]
    for index, assessment in enumerate(comparison.assessments, start=1):
        option = assessment.option
        freshness = (
            f"fonte verificada há {assessment.source_age_days} dia"
            if assessment.source_age_days == 1
            else f"fonte verificada há {assessment.source_age_days} dias"
        )
        if not assessment.source_current:
            freshness += " ⚠️ desatualizada"
        lines.extend(
            [
                "",
                f"{index}. {option.label} · {_money(option.price, option.currency)}",
                f"Risco {level_labels[assessment.level]} · maior perda fixa conhecida "
                f"{_money(assessment.maximum_fixed_exposure, option.currency)} "
                f"({_percent(assessment.exposure_ratio)})",
                f"Cancelar: {_cancellation_text(assessment)}",
                f"Alterar: {_change_text(assessment)}",
                f"Fonte: {freshness}",
                f"🔗 {option.source_url}",
            ]
        )
    lines.append("")
    if comparison.recommendation is None:
        lines.append("⚠️ Sem recomendação: confirme novamente as fontes com mais de 7 dias.")
    else:
        option = comparison.recommendation.option
        lines.append(
            f"✅ Menor risco conhecido: {option.label} · {_money(option.price, option.currency)}"
        )
    lines.extend(
        [
            "",
            "A diferença tarifária futura é variável e não entra na perda fixa calculada.",
            "Confirme as mesmas regras na tela final antes da compra.",
            "Esta análise não altera preços, histórico, Deal Score ou alertas.",
        ]
    )
    message = "\n".join(lines)
    if len(message) > 4096:
        raise ValueError("fare risk message exceeds Telegram's limit")
    return message


def _decimal(value: str) -> Decimal:
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, ValueError) as error:
        raise argparse.ArgumentTypeError("must be a decimal number using a dot") from error
    if not amount.is_finite() or amount < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative decimal")
    return amount


def _positive_decimal(value: str) -> Decimal:
    amount = _decimal(value)
    if amount <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return amount


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError("must be a three-letter ISO 4217 code")
    return normalized


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must use YYYY-MM-DD") from error


def _cancellation(value: str) -> CancellationPolicy:
    try:
        return CancellationPolicy(value.strip().upper())
    except ValueError as error:
        choices = ", ".join(item.value for item in CancellationPolicy)
        raise argparse.ArgumentTypeError(f"must be one of: {choices}") from error


def _change(value: str) -> ChangePolicy:
    try:
        return ChangePolicy(value.strip().upper())
    except ValueError as error:
        choices = ", ".join(item.value for item in ChangePolicy)
        raise argparse.ArgumentTypeError(f"must be one of: {choices}") from error


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise argparse.ArgumentTypeError("must be true or false")


def _add_option_arguments(parser: argparse.ArgumentParser, prefix: str) -> None:
    parser.add_argument(f"--{prefix}-label", required=True)
    parser.add_argument(f"--{prefix}-price", required=True, type=_positive_decimal)
    parser.add_argument(f"--{prefix}-cancellation", required=True, type=_cancellation)
    parser.add_argument(f"--{prefix}-cancellation-penalty", type=_decimal, default=Decimal(0))
    parser.add_argument(f"--{prefix}-change", required=True, type=_change)
    parser.add_argument(f"--{prefix}-change-penalty", type=_decimal, default=Decimal(0))
    parser.add_argument(f"--{prefix}-fare-difference-applies", required=True, type=_boolean)
    parser.add_argument(f"--{prefix}-source-url", required=True)
    parser.add_argument(f"--{prefix}-verified-on", required=True, type=_date)


def _option_from_args(args: argparse.Namespace, prefix: str) -> FarePolicyOption:
    attribute = prefix.replace("-", "_")
    return FarePolicyOption(
        label=getattr(args, f"{attribute}_label"),
        price=getattr(args, f"{attribute}_price"),
        currency=args.currency,
        cancellation=getattr(args, f"{attribute}_cancellation"),
        cancellation_penalty=getattr(args, f"{attribute}_cancellation_penalty"),
        change=getattr(args, f"{attribute}_change"),
        change_penalty=getattr(args, f"{attribute}_change_penalty"),
        fare_difference_applies=getattr(args, f"{attribute}_fare_difference_applies"),
        source_url=getattr(args, f"{attribute}_source_url"),
        verified_on=getattr(args, f"{attribute}_verified_on"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flyclub-fare-risk")
    parser.add_argument("--currency", type=_currency, default="BRL")
    _add_option_arguments(parser, "option-a")
    _add_option_arguments(parser, "option-b")
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    load_dotenv(override=False)
    args = _parser().parse_args(argv)
    try:
        comparison = compare_fare_risk(
            (
                _option_from_args(args, "option-a"),
                _option_from_args(args, "option-b"),
            ),
            today=datetime.now(_BRASILIA).date(),
        )
        message = format_fare_risk_message(comparison)
    except (TypeError, ValueError) as error:
        print(f"Fare risk error: {error}", file=sys.stderr)
        return 2
    try:
        TelegramClient.from_env().send_message(message)
    except TelegramError as error:
        print(f"Notification error: {error}", file=sys.stderr)
        return 1
    print("Fare risk comparison sent to Telegram; no history was persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

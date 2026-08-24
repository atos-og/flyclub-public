from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest

from flyclub.fare_risk import (
    CancellationPolicy,
    ChangePolicy,
    FarePolicyOption,
    FareRiskLevel,
    assess_fare_risk,
    cli,
    compare_fare_risk,
    format_fare_risk_message,
)

TODAY = date(2030, 5, 10)


def _option(
    label: str,
    price: str,
    *,
    cancellation: CancellationPolicy = CancellationPolicy.FULL_REFUND,
    cancellation_penalty: str = "0",
    change: ChangePolicy = ChangePolicy.FREE,
    change_penalty: str = "0",
    fare_difference_applies: bool = True,
    verified_on: date = TODAY,
) -> FarePolicyOption:
    return FarePolicyOption(
        label=label,
        price=Decimal(price),
        currency="BRL",
        cancellation=cancellation,
        cancellation_penalty=Decimal(cancellation_penalty),
        change=change,
        change_penalty=Decimal(change_penalty),
        fare_difference_applies=fare_difference_applies,
        source_url=f"https://example.com/{label.lower().replace(' ', '-')}",
        verified_on=verified_on,
    )


def test_assessment_distinguishes_low_moderate_and_high_fixed_exposure() -> None:
    low = assess_fare_risk(_option("Flex", "1000"), today=TODAY)
    moderate = assess_fare_risk(
        _option(
            "Partial",
            "1000",
            cancellation=CancellationPolicy.PARTIAL_REFUND,
            cancellation_penalty="200",
            change=ChangePolicy.WITH_FEE,
            change_penalty="100",
        ),
        today=TODAY,
    )
    high = assess_fare_risk(
        _option(
            "Basic",
            "800",
            cancellation=CancellationPolicy.NON_REFUNDABLE,
            change=ChangePolicy.NOT_ALLOWED,
        ),
        today=TODAY,
    )

    assert low.level is FareRiskLevel.LOW
    assert low.maximum_fixed_exposure == 0
    assert moderate.level is FareRiskLevel.MODERATE
    assert moderate.maximum_fixed_exposure == Decimal("200")
    assert high.level is FareRiskLevel.HIGH
    assert high.maximum_fixed_exposure == Decimal("800")


def test_comparison_prefers_lower_risk_before_lower_price() -> None:
    basic = _option(
        "Basic",
        "800",
        cancellation=CancellationPolicy.NON_REFUNDABLE,
        change=ChangePolicy.NOT_ALLOWED,
    )
    flexible = _option("Flexible", "1100")

    comparison = compare_fare_risk((basic, flexible), today=TODAY)

    assert comparison.assessments[0].option.label == "Flexible"
    assert comparison.recommendation is not None
    assert comparison.recommendation.option.label == "Flexible"


def test_comparison_prefers_lower_absolute_exposure_before_lower_ratio() -> None:
    lower_amount = _option(
        "Lower amount",
        "1000",
        cancellation=CancellationPolicy.PARTIAL_REFUND,
        cancellation_penalty="300",
        change=ChangePolicy.WITH_FEE,
        change_penalty="100",
    )
    lower_ratio = _option(
        "Lower ratio",
        "2000",
        cancellation=CancellationPolicy.PARTIAL_REFUND,
        cancellation_penalty="400",
        change=ChangePolicy.WITH_FEE,
        change_penalty="100",
    )

    comparison = compare_fare_risk((lower_ratio, lower_amount), today=TODAY)

    assert comparison.recommendation is not None
    assert comparison.recommendation.option.label == "Lower amount"


def test_stale_source_blocks_automatic_recommendation() -> None:
    stale = _option("Stale", "900", verified_on=TODAY - timedelta(days=8))
    current = _option("Current", "1000")

    comparison = compare_fare_risk((stale, current), today=TODAY)

    assert comparison.recommendation is None
    assert any(not item.source_current for item in comparison.assessments)
    message = format_fare_risk_message(comparison)
    assert "⚠️ desatualizada" in message
    assert "⚠️ Sem recomendação" in message


def test_policy_validation_rejects_inconsistent_penalties_and_urls() -> None:
    with pytest.raises(ValueError, match="partial refund"):
        _option(
            "Broken",
            "1000",
            cancellation=CancellationPolicy.PARTIAL_REFUND,
            cancellation_penalty="0",
        )
    with pytest.raises(ValueError, match="source"):
        replace(_option("Valid", "1000"), source_url="not-a-url")


def test_future_verification_date_is_rejected_during_assessment() -> None:
    option = _option("Future", "1000", verified_on=TODAY + timedelta(days=1))

    with pytest.raises(ValueError, match="future"):
        assess_fare_risk(option, today=TODAY)


def test_formatter_explains_fixed_exposure_and_variable_fare_difference() -> None:
    flexible = _option("Flexível", "1100")
    basic = _option(
        "Básica",
        "800",
        cancellation=CancellationPolicy.NON_REFUNDABLE,
        change=ChangePolicy.NOT_ALLOWED,
    )

    message = format_fare_risk_message(compare_fare_risk((basic, flexible), today=TODAY))

    assert message.startswith("🛡️ FLEXIBILIDADE TARIFÁRIA")
    assert "✅ Menor risco conhecido: Flexível · R$ 1.100,00" in message
    assert "não reembolsável; perda potencial R$ 800,00" in message
    assert "eventual diferença tarifária" in message
    assert "Confirme as mesmas regras na tela final" in message
    assert "não altera preços, histórico, Deal Score ou alertas" in message


def test_formatter_supports_non_brl_currency_without_conversion() -> None:
    first = replace(_option("First", "1000"), currency="USD")
    second = replace(_option("Second", "1200"), currency="USD")

    message = format_fare_risk_message(compare_fare_risk((first, second), today=TODAY))

    assert "USD 1000.00" in message


class FakeTelegram:
    messages: ClassVar[list[str]] = []

    @classmethod
    def from_env(cls) -> FakeTelegram:
        return cls()

    def send_message(self, message: str) -> None:
        self.messages.append(message)


def test_cli_sends_one_non_persistent_comparison(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeTelegram.messages = []
    today = date.today().isoformat()
    monkeypatch.setattr("flyclub.fare_risk.load_dotenv", lambda *, override: None)
    monkeypatch.setattr("flyclub.fare_risk.TelegramClient", FakeTelegram)

    result = cli(
        [
            "--option-a-label",
            "Flex",
            "--option-a-price",
            "1100",
            "--option-a-cancellation",
            "FULL_REFUND",
            "--option-a-change",
            "FREE",
            "--option-a-fare-difference-applies",
            "true",
            "--option-a-source-url",
            "https://example.com/flex",
            "--option-a-verified-on",
            today,
            "--option-b-label",
            "Basic",
            "--option-b-price",
            "800",
            "--option-b-cancellation",
            "NON_REFUNDABLE",
            "--option-b-change",
            "NOT_ALLOWED",
            "--option-b-fare-difference-applies",
            "false",
            "--option-b-source-url",
            "https://example.com/basic",
            "--option-b-verified-on",
            today,
        ]
    )

    assert result == 0
    assert len(FakeTelegram.messages) == 1
    assert "Menor risco conhecido: Flex" in FakeTelegram.messages[0]
    assert "no history was persisted" in capsys.readouterr().out

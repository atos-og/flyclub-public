"""Pure decimal statistics over comparable historical route prices."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ConfidenceLevel(StrEnum):
    """How much historical support is available for a statistical score."""

    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class PriceStatistics:
    """Historical distribution used to evaluate one current price.

    ``sample_size`` and every distribution field refer only to prior observations. The
    current price is deliberately kept outside its own baseline.
    """

    sample_size: int
    confidence: ConfidenceLevel
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    percentile_rank: Decimal | None
    recorded_low: Decimal | None


def _validated_prices(values: Iterable[Decimal]) -> tuple[Decimal, ...]:
    prices = tuple(values)
    if any(not isinstance(price, Decimal) for price in prices):
        raise TypeError("prices must use Decimal")
    if any(not price.is_finite() or price <= 0 for price in prices):
        raise ValueError("prices must be finite and greater than zero")
    return prices


def percentile(values: Sequence[Decimal], percentage: Decimal | int) -> Decimal:
    """Return a linearly interpolated percentile using the inclusive endpoints method."""

    prices = sorted(_validated_prices(values))
    selected = Decimal(percentage)
    if not prices:
        raise ValueError("at least one price is required")
    if selected < 0 or selected > 100:
        raise ValueError("percentage must be between 0 and 100")
    if len(prices) == 1:
        return prices[0]

    position = Decimal(len(prices) - 1) * selected / Decimal(100)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(prices) - 1)
    fraction = position - lower_index
    return prices[lower_index] + (prices[upper_index] - prices[lower_index]) * fraction


def percentile_rank(values: Sequence[Decimal], current_price: Decimal) -> Decimal:
    """Return the current price's midrank percentile within prior observations.

    Equal historical prices receive half weight. This makes ties deterministic and avoids
    classifying an unchanged price as either strictly better or worse than the tied baseline.
    """

    prices = _validated_prices(values)
    _validated_prices((current_price,))
    if not prices:
        raise ValueError("at least one historical price is required")

    below = sum(price < current_price for price in prices)
    equal = sum(price == current_price for price in prices)
    return (Decimal(below) + Decimal(equal) / 2) * Decimal(100) / Decimal(len(prices))


def _confidence(
    sample_size: int,
    *,
    min_score_samples: int,
    low_confidence_max_samples: int,
    moderate_confidence_max_samples: int,
) -> ConfidenceLevel:
    if min_score_samples < 1:
        raise ValueError("min_score_samples must be at least 1")
    if low_confidence_max_samples < min_score_samples:
        raise ValueError("low confidence maximum must include the minimum score sample size")
    if moderate_confidence_max_samples < low_confidence_max_samples:
        raise ValueError("moderate confidence maximum must not be below the low maximum")
    if sample_size < min_score_samples:
        return ConfidenceLevel.INSUFFICIENT
    if sample_size <= low_confidence_max_samples:
        return ConfidenceLevel.LOW
    if sample_size <= moderate_confidence_max_samples:
        return ConfidenceLevel.MODERATE
    return ConfidenceLevel.HIGH


def analyze_price(
    current_price: Decimal,
    historical_prices: Sequence[Decimal],
    *,
    min_score_samples: int,
    low_confidence_max_samples: int,
    moderate_confidence_max_samples: int,
) -> PriceStatistics:
    """Analyze a current price against an explicitly prior-only historical series."""

    _validated_prices((current_price,))
    history = _validated_prices(historical_prices)
    confidence = _confidence(
        len(history),
        min_score_samples=min_score_samples,
        low_confidence_max_samples=low_confidence_max_samples,
        moderate_confidence_max_samples=moderate_confidence_max_samples,
    )
    if not history:
        return PriceStatistics(
            sample_size=0,
            confidence=confidence,
            p10=None,
            p50=None,
            p90=None,
            percentile_rank=None,
            recorded_low=None,
        )

    return PriceStatistics(
        sample_size=len(history),
        confidence=confidence,
        p10=percentile(history, 10),
        p50=percentile(history, 50),
        p90=percentile(history, 90),
        percentile_rank=percentile_rank(history, current_price),
        recorded_low=min(history),
    )

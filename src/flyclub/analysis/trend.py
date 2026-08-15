"""Recent price movement and multi-observation trend calculations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from flyclub.analysis.statistics import percentile


class TrendDirection(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    FALLING = "FALLING"
    STABLE = "STABLE"
    RISING = "RISING"


@dataclass(frozen=True, slots=True)
class TrendAnalysis:
    """Comparison of two historical windows, ordered from oldest to newest."""

    sample_size: int
    direction: TrendDirection
    change_percent: Decimal | None
    previous_median: Decimal | None
    recent_median: Decimal | None


def _validate_price(value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError("prices must use Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError("prices must be finite and greater than zero")


def price_change_percent(reference_price: Decimal, current_price: Decimal) -> Decimal:
    """Return signed price change; a negative result means an objective price drop."""

    _validate_price(reference_price)
    _validate_price(current_price)
    return (current_price - reference_price) * Decimal(100) / reference_price


def price_drop_percent(reference_price: Decimal, current_price: Decimal) -> Decimal:
    """Return a positive percentage for a drop and a negative percentage for a rise."""

    return -price_change_percent(reference_price, current_price)


def analyze_trend(
    historical_prices: Sequence[Decimal],
    *,
    window_samples: int = 4,
    stable_band_percent: Decimal = Decimal("1"),
) -> TrendAnalysis:
    """Compare two adjacent historical medians without using the current observation.

    Input must be chronological, oldest first. The most recent ``window_samples`` historical
    values are compared with the immediately preceding window. This deliberately keeps the
    current price out of trend so its point-in-time drop is not counted twice.
    """

    if window_samples < 2:
        raise ValueError("window_samples must be at least 2")
    if stable_band_percent < 0:
        raise ValueError("stable_band_percent must not be negative")
    for price in historical_prices:
        _validate_price(price)

    required = window_samples * 2
    if len(historical_prices) < required:
        return TrendAnalysis(
            sample_size=len(historical_prices),
            direction=TrendDirection.INSUFFICIENT,
            change_percent=None,
            previous_median=None,
            recent_median=None,
        )

    selected = historical_prices[-required:]
    previous_median = percentile(selected[:window_samples], 50)
    recent_median = percentile(selected[window_samples:], 50)
    change = price_change_percent(previous_median, recent_median)
    if change < -stable_band_percent:
        direction = TrendDirection.FALLING
    elif change > stable_band_percent:
        direction = TrendDirection.RISING
    else:
        direction = TrendDirection.STABLE
    return TrendAnalysis(
        sample_size=required,
        direction=direction,
        change_percent=change,
        previous_median=previous_median,
        recent_median=recent_median,
    )

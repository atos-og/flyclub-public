from __future__ import annotations

from decimal import Decimal

import pytest

from flyclub.analysis.trend import (
    TrendDirection,
    analyze_trend,
    price_change_percent,
    price_drop_percent,
)


def _prices(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def test_recent_drop_is_a_point_in_time_comparison() -> None:
    assert price_change_percent(Decimal("100"), Decimal("90")) == Decimal("-10")
    assert price_drop_percent(Decimal("100"), Decimal("90")) == Decimal("10")
    assert price_drop_percent(Decimal("100"), Decimal("110")) == Decimal("-10")


def test_trend_compares_two_multi_observation_historical_windows() -> None:
    result = analyze_trend(_prices("100", "100", "100", "100", "90", "90", "90", "90"))

    assert result.direction is TrendDirection.FALLING
    assert result.previous_median == Decimal("100")
    assert result.recent_median == Decimal("90")
    assert result.change_percent == Decimal("-10")


def test_current_price_cannot_change_prior_only_trend() -> None:
    history = _prices("100", "100", "100", "100", "98", "98", "98", "98")

    first = analyze_trend(history)
    second = analyze_trend(history)

    assert first == second
    assert first.direction is TrendDirection.FALLING


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("100", "100", "100", "100", "100", "100", "100", "101"), TrendDirection.STABLE),
        (("90", "90", "90", "90", "100", "100", "100", "100"), TrendDirection.RISING),
    ],
)
def test_trend_classifies_stable_and_rising_windows(
    values: tuple[str, ...], expected: TrendDirection
) -> None:
    assert analyze_trend(_prices(*values)).direction is expected


def test_trend_requires_two_complete_windows() -> None:
    result = analyze_trend(_prices("100", "99", "98"))

    assert result.direction is TrendDirection.INSUFFICIENT
    assert result.change_percent is None


def test_trend_rejects_invalid_window_and_non_decimal_prices() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        analyze_trend(_prices("100", "90"), window_samples=1)

    with pytest.raises(TypeError, match="Decimal"):
        analyze_trend((Decimal("100"), 90.0))  # type: ignore[arg-type]

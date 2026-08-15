from __future__ import annotations

from decimal import Decimal

import pytest

from flyclub.analysis.statistics import (
    ConfidenceLevel,
    analyze_price,
    percentile,
    percentile_rank,
)


def _prices(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def test_percentiles_use_decimal_linear_interpolation() -> None:
    history = _prices("100", "200", "300", "400", "500")

    assert percentile(history, 10) == Decimal("140")
    assert percentile(history, 50) == Decimal("300")
    assert percentile(history, 90) == Decimal("460")


def test_percentile_rank_counts_ties_at_their_midrank() -> None:
    history = _prices("100", "200", "200", "400")

    assert percentile_rank(history, Decimal("200")) == Decimal("50")
    assert percentile_rank(history, Decimal("50")) == Decimal("0")
    assert percentile_rank(history, Decimal("500")) == Decimal("100")


def test_current_price_is_not_added_to_its_own_baseline() -> None:
    statistics = analyze_price(
        Decimal("50"),
        _prices("100", "200", "300"),
        min_score_samples=3,
        low_confidence_max_samples=5,
        moderate_confidence_max_samples=10,
    )

    assert statistics.sample_size == 3
    assert statistics.recorded_low == Decimal("100")
    assert statistics.percentile_rank == Decimal("0")
    assert statistics.p50 == Decimal("200")


@pytest.mark.parametrize(
    ("sample_size", "expected"),
    [
        (0, ConfidenceLevel.INSUFFICIENT),
        (11, ConfidenceLevel.INSUFFICIENT),
        (12, ConfidenceLevel.LOW),
        (30, ConfidenceLevel.LOW),
        (31, ConfidenceLevel.MODERATE),
        (100, ConfidenceLevel.MODERATE),
        (101, ConfidenceLevel.HIGH),
    ],
)
def test_confidence_thresholds_are_explicit(sample_size: int, expected: ConfidenceLevel) -> None:
    statistics = analyze_price(
        Decimal("100"),
        tuple(Decimal(index + 1) for index in range(sample_size)),
        min_score_samples=12,
        low_confidence_max_samples=30,
        moderate_confidence_max_samples=100,
    )

    assert statistics.confidence is expected


def test_cold_start_returns_no_invented_distribution() -> None:
    statistics = analyze_price(
        Decimal("100"),
        (),
        min_score_samples=12,
        low_confidence_max_samples=30,
        moderate_confidence_max_samples=100,
    )

    assert statistics.confidence is ConfidenceLevel.INSUFFICIENT
    assert statistics.p10 is None
    assert statistics.p50 is None
    assert statistics.p90 is None
    assert statistics.percentile_rank is None
    assert statistics.recorded_low is None


def test_statistics_reject_float_and_invalid_prices() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        percentile((Decimal("100"), 200.0), 50)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="greater than zero"):
        percentile(_prices("100", "0"), 50)


def test_confidence_thresholds_cannot_overlap_backwards() -> None:
    with pytest.raises(ValueError, match="minimum score"):
        analyze_price(
            Decimal("100"),
            _prices("90"),
            min_score_samples=12,
            low_confidence_max_samples=10,
            moderate_confidence_max_samples=100,
        )

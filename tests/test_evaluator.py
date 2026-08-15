from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from flyclub.analysis.deal_score import DealScoreWeights, RecentDropBasis
from flyclub.analysis.evaluator import (
    AnalysisPolicy,
    PersistedPriceAnalyzer,
    evaluate_price,
)
from flyclub.analysis.statistics import ConfidenceLevel
from flyclub.analysis.trend import TrendDirection
from flyclub.models import PriceObservation

NOW = datetime(2027, 1, 10, 12, tzinfo=UTC)


def _policy() -> AnalysisPolicy:
    return AnalysisPolicy(
        min_score_samples=12,
        low_confidence_max_samples=30,
        moderate_confidence_max_samples=100,
        weights=DealScoreWeights(),
    )


def _history(
    prices: tuple[str, ...], *, start: datetime, step: timedelta
) -> tuple[PriceObservation, ...]:
    return tuple(
        PriceObservation(price=Decimal(price), observed_at=start + step * index)
        for index, price in enumerate(prices)
    )


def test_evaluation_prefers_a_close_twenty_four_hour_reference() -> None:
    history = _history(
        ("110", "108", "106", "104", "102", "100", "100", "98", "96", "94", "92", "90"),
        start=NOW - timedelta(hours=39),
        step=timedelta(hours=3),
    )
    last_alert = PriceObservation(Decimal("130"), NOW - timedelta(days=4))

    result = evaluate_price(
        current_price=Decimal("80"),
        current_at=NOW,
        history=history,
        last_sent_alert=last_alert,
        policy=_policy(),
    )

    assert result.recent_drop is not None
    assert result.recent_drop.basis is RecentDropBasis.TWENTY_FOUR_HOURS
    assert result.recent_drop.drop_percent == Decimal("20")
    assert result.statistics.confidence is ConfidenceLevel.LOW
    assert result.deal_score.provisional is True
    assert result.trend.direction is TrendDirection.FALLING


def test_evaluation_falls_back_to_last_alert_when_no_24h_observation_exists() -> None:
    history = _history(
        tuple("100" for _ in range(12)),
        start=NOW - timedelta(hours=11),
        step=timedelta(hours=1),
    )
    last_alert = PriceObservation(Decimal("100"), NOW - timedelta(days=3))

    result = evaluate_price(
        current_price=Decimal("90"),
        current_at=NOW,
        history=history,
        last_sent_alert=last_alert,
        policy=_policy(),
    )

    assert result.recent_drop is not None
    assert result.recent_drop.basis is RecentDropBasis.LAST_ALERT
    assert result.recent_drop.drop_percent == Decimal("10")


def test_cold_start_evaluates_without_inventing_score_or_drop() -> None:
    result = evaluate_price(
        current_price=Decimal("90"),
        current_at=NOW,
        history=(),
        last_sent_alert=None,
        policy=_policy(),
    )

    assert result.statistics.sample_size == 0
    assert result.deal_score.score is None
    assert result.recent_drop is None
    assert result.trend.direction is TrendDirection.INSUFFICIENT


class FakeHistoryRepository:
    def __init__(self) -> None:
        self.check_id: UUID | None = None
        self.route_key: str | None = None

    def price_history(
        self, *, route_key: str, exclude_check_id: UUID, limit: int = 500
    ) -> tuple[PriceObservation, ...]:
        assert limit == 500
        self.route_key = route_key
        self.check_id = exclude_check_id
        return ()

    def last_sent_alert_price(self, *, route_key: str) -> PriceObservation | None:
        assert route_key == self.route_key
        return None


def test_persisted_analyzer_explicitly_excludes_current_check() -> None:
    repository = FakeHistoryRepository()
    analyzer = PersistedPriceAnalyzer(repository, _policy())
    check_id = uuid4()

    analyzer.evaluate(
        route_key="route-key",
        current_check_id=check_id,
        current_price=Decimal("90"),
        current_at=NOW,
    )

    assert repository.route_key == "route-key"
    assert repository.check_id == check_id

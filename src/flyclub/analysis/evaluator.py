"""Build one complete price evaluation from persisted prior observations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from flyclub.analysis.deal_score import (
    DealScoreResult,
    DealScoreWeights,
    RecentDropBasis,
    RecentDropSignal,
    calculate_deal_score,
)
from flyclub.analysis.statistics import PriceStatistics, analyze_price, percentile
from flyclub.analysis.trend import TrendAnalysis, analyze_trend, price_drop_percent
from flyclub.models import PriceObservation


class AnalysisHistoryRepository(Protocol):
    def price_history(
        self,
        *,
        route_key: str,
        exclude_check_id: UUID,
        limit: int = 500,
    ) -> tuple[PriceObservation, ...]: ...

    def last_sent_alert_price(self, *, route_key: str) -> PriceObservation | None: ...

    def record_shadow_score(
        self,
        *,
        route_check_id: UUID,
        evaluated_at: datetime,
        evaluation: ShadowScoreEvaluation,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    min_score_samples: int
    low_confidence_max_samples: int
    moderate_confidence_max_samples: int
    weights: DealScoreWeights = field(default_factory=DealScoreWeights)
    trend_window_samples: int = 4
    reference_tolerance_hours: int = 6
    history_limit: int = 500
    shadow_history_limit: int = 8000


@dataclass(frozen=True, slots=True)
class RoutePriceEvaluation:
    statistics: PriceStatistics
    trend: TrendAnalysis
    recent_drop: RecentDropSignal | None
    deal_score: DealScoreResult
    shadow: ShadowScoreEvaluation | None = None


SHADOW_SCORE_VERSION = "daily-median-v2"
SHADOW_TIMEZONE = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True, slots=True)
class ShadowScoreEvaluation:
    version: str
    statistics: PriceStatistics
    trend: TrendAnalysis
    recent_drop: RecentDropSignal | None
    deal_score: DealScoreResult


def daily_median_history(
    history: tuple[PriceObservation, ...],
) -> tuple[PriceObservation, ...]:
    """Collapse correlated intraday checks into one Brasília-day median observation."""

    buckets: dict[object, list[PriceObservation]] = defaultdict(list)
    for observation in history:
        if observation.observed_at.tzinfo is None:
            raise ValueError("shadow history timestamps must be timezone-aware")
        local_day = observation.observed_at.astimezone(SHADOW_TIMEZONE).date()
        buckets[local_day].append(observation)

    representatives: list[PriceObservation] = []
    for local_day in sorted(buckets):
        observations = buckets[local_day]
        representatives.append(
            PriceObservation(
                price=percentile(tuple(item.price for item in observations), 50),
                observed_at=max(item.observed_at for item in observations),
            )
        )
    return tuple(representatives)


def _twenty_four_hour_reference(
    history: tuple[PriceObservation, ...],
    *,
    current_at: datetime,
    tolerance_hours: int,
) -> PriceObservation | None:
    target = current_at - timedelta(hours=24)
    tolerance = timedelta(hours=tolerance_hours)
    eligible = [
        observation
        for observation in history
        if observation.observed_at <= current_at
        and abs(observation.observed_at - target) <= tolerance
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda observation: (
            abs(observation.observed_at - target),
            -observation.observed_at.timestamp(),
        ),
    )


def evaluate_price(
    *,
    current_price: Decimal,
    current_at: datetime,
    history: tuple[PriceObservation, ...],
    last_sent_alert: PriceObservation | None,
    policy: AnalysisPolicy,
) -> RoutePriceEvaluation:
    """Evaluate current price; history must already exclude the current route check."""

    historical_prices = tuple(observation.price for observation in history)
    statistics = analyze_price(
        current_price,
        historical_prices,
        min_score_samples=policy.min_score_samples,
        low_confidence_max_samples=policy.low_confidence_max_samples,
        moderate_confidence_max_samples=policy.moderate_confidence_max_samples,
    )
    trend = analyze_trend(
        historical_prices,
        window_samples=policy.trend_window_samples,
    )

    reference = _twenty_four_hour_reference(
        history,
        current_at=current_at,
        tolerance_hours=policy.reference_tolerance_hours,
    )
    basis = RecentDropBasis.TWENTY_FOUR_HOURS
    if (
        reference is None
        and last_sent_alert is not None
        and last_sent_alert.observed_at <= current_at
    ):
        reference = last_sent_alert
        basis = RecentDropBasis.LAST_ALERT
    recent_drop = None
    if reference is not None:
        recent_drop = RecentDropSignal(
            basis=basis,
            drop_percent=price_drop_percent(reference.price, current_price),
        )

    return RoutePriceEvaluation(
        statistics=statistics,
        trend=trend,
        recent_drop=recent_drop,
        deal_score=calculate_deal_score(
            current_price,
            statistics,
            recent_drop=recent_drop,
            trend=trend,
            weights=policy.weights,
        ),
    )


def evaluate_shadow_price(
    *,
    current_price: Decimal,
    current_at: datetime,
    history: tuple[PriceObservation, ...],
    last_sent_alert: PriceObservation | None,
    policy: AnalysisPolicy,
) -> ShadowScoreEvaluation:
    bucketed = daily_median_history(history)
    evaluation = evaluate_price(
        current_price=current_price,
        current_at=current_at,
        history=bucketed,
        last_sent_alert=last_sent_alert,
        policy=policy,
    )
    return ShadowScoreEvaluation(
        version=SHADOW_SCORE_VERSION,
        statistics=evaluation.statistics,
        trend=evaluation.trend,
        recent_drop=evaluation.recent_drop,
        deal_score=evaluation.deal_score,
    )


class PersistedPriceAnalyzer:
    """Load prior-only series from storage and run the pure evaluation pipeline."""

    def __init__(self, repository: AnalysisHistoryRepository, policy: AnalysisPolicy) -> None:
        self._repository = repository
        self._policy = policy

    def evaluate(
        self,
        *,
        route_key: str,
        current_check_id: UUID,
        current_price: Decimal,
        current_at: datetime,
    ) -> RoutePriceEvaluation:
        history = self._repository.price_history(
            route_key=route_key,
            exclude_check_id=current_check_id,
            limit=self._policy.shadow_history_limit,
        )
        last_alert = self._repository.last_sent_alert_price(route_key=route_key)
        production = evaluate_price(
            current_price=current_price,
            current_at=current_at,
            history=history[-self._policy.history_limit :],
            last_sent_alert=last_alert,
            policy=self._policy,
        )
        shadow = evaluate_shadow_price(
            current_price=current_price,
            current_at=current_at,
            history=history,
            last_sent_alert=last_alert,
            policy=self._policy,
        )
        self._repository.record_shadow_score(
            route_check_id=current_check_id,
            evaluated_at=current_at,
            evaluation=shadow,
        )
        return replace(production, shadow=shadow)

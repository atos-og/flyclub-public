"""Rolling date-market scanner isolated from Fly Club's fixed-date monitor."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from flyclub.alerts.telegram import TelegramClient, TelegramError
from flyclub.analysis.evaluator import AnalysisPolicy, RoutePriceEvaluation, evaluate_price
from flyclub.flexible_market_alerts import (
    FlexibleAlertPolicy,
    FlexibleMarketAlertCoordinator,
)
from flyclub.flexible_market_config import (
    FlexibleMarketConfigError,
    FlexibleMarketSettings,
    flexible_market_fingerprint,
    load_flexible_market_config,
)
from flyclub.flexible_market_models import (
    CalendarFare,
    CalendarSearchOutcome,
    FlexibleMarketDefinition,
    FlexibleMarketPeriod,
    market_definition,
)
from flyclub.models import FlightOption, PriceObservation, SearchOutcome, SearchStatus
from flyclub.providers.google_flights_flexible import GoogleFlightsFlexibleProvider
from flyclub.storage.flexible_market import FlexibleMarketRepository
from flyclub.storage.postgres import PostgresRepository, RunStatus, StorageError

PERIOD_2026_END = date(2026, 12, 31)
PERIOD_FUTURE_START = date(2027, 1, 1)
BRASILIA_TIMEZONE = ZoneInfo("America/Sao_Paulo")


class FlexibleProvider(Protocol):
    name: str

    def search_calendar(
        self,
        market: FlexibleMarketDefinition,
        *,
        start_date: date,
        end_date: date,
    ) -> CalendarSearchOutcome: ...

    def verify(
        self,
        market: FlexibleMarketDefinition,
        *,
        departure_date: date,
        return_date: date,
        max_results: int,
    ) -> SearchOutcome: ...


@dataclass(frozen=True, slots=True)
class FlexibleMarketSummary:
    status: RunStatus
    planned_series: int
    successful_series: int
    empty_series: int
    failed_series: int
    calendar_requests: int
    verification_requests: int
    analyzed_series: int
    alerts_sent: int
    persisted: bool


def _periods(market: FlexibleMarketDefinition, *, today: date) -> tuple[FlexibleMarketPeriod, ...]:
    window_start = today + timedelta(days=market.minimum_days_ahead)
    window_end = today + timedelta(days=market.maximum_days_ahead)
    fixed_window = market.travel_window_start is not None and market.travel_window_end is not None
    if fixed_window:
        window_start = max(window_start, market.travel_window_start)
        window_end = min(
            window_end,
            market.travel_window_end - timedelta(days=market.trip_duration_days),
        )
    if window_end < window_start:
        return ()

    def period_key(policy: str, start: date, end: date) -> str:
        if not fixed_window:
            return policy
        return f"fixed_{start:%Y%m%d}_{end:%Y%m%d}_{policy}"

    def period_label(default: str) -> str:
        if not fixed_window:
            return default
        return (
            f"viagens entre {market.travel_window_start:%d/%m/%Y} "
            f"e {market.travel_window_end:%d/%m/%Y}"
        )

    periods: list[FlexibleMarketPeriod] = []
    if window_start <= PERIOD_2026_END:
        period_end = min(window_end, PERIOD_2026_END)
        periods.append(
            FlexibleMarketPeriod(
                key=period_key("remaining_2026", window_start, period_end),
                label=period_label("partidas até 31/12/2026"),
                start_date=window_start,
                end_date=period_end,
                minimum_deal_score=market.score_threshold_2026,
            )
        )
    if window_end >= PERIOD_FUTURE_START:
        period_start = max(window_start, PERIOD_FUTURE_START)
        periods.append(
            FlexibleMarketPeriod(
                key=period_key("from_2027", period_start, window_end),
                label=period_label("partidas a partir de 01/01/2027"),
                start_date=period_start,
                end_date=window_end,
                minimum_deal_score=market.score_threshold_future,
            )
        )
    return tuple(periods)


def _status(successful: int, empty: int, failed: int) -> RunStatus:
    if failed == 0:
        return RunStatus.SUCCESS
    if successful + empty:
        return RunStatus.PARTIAL
    return RunStatus.FAILURE


def _failure_outcome(provider: str, status: SearchStatus, code: str | None) -> SearchOutcome:
    return SearchOutcome(
        provider=provider,
        status=status,
        error_code=code,
        error_message="Flexible-market provider search did not produce a verified fare",
    )


def _verify_period(
    *,
    provider: FlexibleProvider,
    market: FlexibleMarketDefinition,
    fares: tuple[CalendarFare, ...],
    candidate_limit: int,
    max_results: int,
) -> tuple[CalendarFare | None, SearchOutcome, int]:
    candidates = fares[:candidate_limit]
    if not candidates:
        return None, SearchOutcome(provider=provider.name, status=SearchStatus.EMPTY), 0
    successful: list[tuple[CalendarFare, FlightOption, SearchOutcome]] = []
    attempts = 0
    failures: list[SearchOutcome] = []
    for fare in candidates:
        attempts += 1
        outcome = provider.verify(
            market,
            departure_date=fare.departure_date,
            return_date=fare.return_date,
            max_results=max_results,
        )
        if outcome.status is SearchStatus.SUCCESS:
            successful.append((fare, outcome.options[0], outcome))
        elif outcome.status is not SearchStatus.EMPTY:
            failures.append(outcome)
    if successful:
        fare, option, _ = min(successful, key=lambda item: item[1].price)
        return (
            fare,
            SearchOutcome(
                provider=provider.name,
                status=SearchStatus.SUCCESS,
                options=(option,),
            ),
            attempts,
        )
    if failures:
        return None, failures[0], attempts
    return None, SearchOutcome(provider=provider.name, status=SearchStatus.EMPTY), attempts


def _evaluate(
    *,
    repository: FlexibleMarketRepository,
    market: FlexibleMarketDefinition,
    period: FlexibleMarketPeriod,
    check_id: object,
    current_price: Decimal,
    current_at: datetime,
    policy: AnalysisPolicy,
) -> RoutePriceEvaluation:
    history = repository.price_history(
        market_key=market.key,
        period_key=period.key,
        exclude_check_id=check_id,
        limit=policy.history_limit,
    )
    last = repository.last_sent_alert(market_key=market.key, period_key=period.key)
    last_observation = (
        PriceObservation(price=last.price, observed_at=last.observed_at)
        if last is not None
        else None
    )
    return evaluate_price(
        current_price=current_price,
        current_at=current_at,
        history=history,
        last_sent_alert=last_observation,
        policy=policy,
    )


def run_flexible_market_scan(
    *,
    settings: FlexibleMarketSettings,
    provider: FlexibleProvider,
    today: date,
    current_at: datetime,
    run_repository: PostgresRepository | None,
    market_repository: FlexibleMarketRepository | None,
    alert_coordinator: FlexibleMarketAlertCoordinator | None,
) -> FlexibleMarketSummary:
    if current_at.tzinfo is None:
        raise ValueError("current_at must be timezone-aware")
    markets = tuple(market_definition(config) for config in settings.markets)
    active_markets = tuple(
        (market, periods) for market in markets if (periods := _periods(market, today=today))
    )
    planned = sum(len(periods) for _, periods in active_markets)
    run_id = None
    if run_repository is not None:
        run_id = run_repository.start_run(
            config_fingerprint=flexible_market_fingerprint(settings),
            provider=provider.name,
            planned_routes=planned,
            started_at=current_at,
        )
    successful = empty = failed = analyzed = alerts_sent = 0
    calendar_requests = verification_requests = 0
    analysis_policy = AnalysisPolicy(
        min_score_samples=settings.min_score_samples,
        low_confidence_max_samples=settings.low_confidence_max_samples,
        moderate_confidence_max_samples=settings.moderate_confidence_max_samples,
    )
    aborted = False
    try:
        for market, periods in active_markets:
            window_start = min(period.start_date for period in periods)
            window_end = max(period.end_date for period in periods)
            calendar = provider.search_calendar(
                market, start_date=window_start, end_date=window_end
            )
            calendar_requests += calendar.request_count
            for period_index, period in enumerate(periods):
                provider_requests = calendar.request_count if period_index == 0 else 0
                fare = None
                if calendar.status is SearchStatus.SUCCESS:
                    eligible = tuple(
                        item
                        for item in calendar.fares
                        if period.start_date <= item.departure_date <= period.end_date
                    )
                    fare, outcome, verification_count = _verify_period(
                        provider=provider,
                        market=market,
                        fares=eligible,
                        candidate_limit=settings.verification_candidates_per_period,
                        max_results=settings.verification_results,
                    )
                    verification_requests += verification_count
                    provider_requests += verification_count
                elif calendar.status is SearchStatus.EMPTY:
                    outcome = SearchOutcome(provider=provider.name, status=SearchStatus.EMPTY)
                else:
                    outcome = _failure_outcome(provider.name, calendar.status, calendar.error_code)
                if outcome.status is SearchStatus.SUCCESS:
                    successful += 1
                elif outcome.status is SearchStatus.EMPTY:
                    empty += 1
                else:
                    failed += 1
                if run_id is None or market_repository is None:
                    continue
                check_id = market_repository.record_check(
                    run_id=run_id,
                    market=market,
                    period=period,
                    outcome=outcome,
                    calendar_fare=fare,
                    provider_requests=provider_requests,
                    checked_at=current_at,
                )
                if outcome.status is not SearchStatus.SUCCESS or fare is None:
                    continue
                evaluation = _evaluate(
                    repository=market_repository,
                    market=market,
                    period=period,
                    check_id=check_id,
                    current_price=outcome.options[0].price,
                    current_at=current_at,
                    policy=analysis_policy,
                )
                market_repository.update_evaluation(check_id=check_id, evaluation=evaluation)
                analyzed += 1
                if alert_coordinator is not None and alert_coordinator.handle(
                    check_id=check_id,
                    market=market,
                    period=period,
                    fare=fare,
                    option=outcome.options[0],
                    current_at=current_at,
                    evaluation=evaluation,
                ):
                    alerts_sent += 1
    except Exception:
        aborted = True
        raise
    finally:
        unprocessed = max(0, planned - successful - empty - failed)
        final_status = RunStatus.FAILURE if aborted else _status(successful, empty, failed)
        if run_id is not None and run_repository is not None:
            run_repository.finish_run(
                run_id=run_id,
                status=final_status,
                successful_routes=successful,
                empty_routes=empty,
                failed_routes=failed + unprocessed,
                error_code="FLEXIBLE_MARKET_ABORTED" if aborted else None,
                error_message="Flexible-market scan aborted unexpectedly" if aborted else None,
            )
    return FlexibleMarketSummary(
        status=_status(successful, empty, failed),
        planned_series=planned,
        successful_series=successful,
        empty_series=empty,
        failed_series=failed,
        calendar_requests=calendar_requests,
        verification_requests=verification_requests,
        analyzed_series=analyzed,
        alerts_sent=alerts_sent,
        persisted=run_repository is not None,
    )


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flyclub-flexible-market")
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_dotenv(override=False)
    try:
        settings = load_flexible_market_config(args.config)
        provider = GoogleFlightsFlexibleProvider(
            retry_attempts=settings.retry_attempts,
            retry_base_delay_seconds=float(settings.retry_base_delay_seconds),
            calendar_chunk_days=settings.calendar_chunk_days,
        )
        run_repository = None if args.dry_run else PostgresRepository.from_env()
        market_repository = None if args.dry_run else FlexibleMarketRepository.from_env()
        alert_coordinator = None
        if market_repository is not None:
            alert_coordinator = FlexibleMarketAlertCoordinator(
                market_repository,
                TelegramClient.from_env(),
                FlexibleAlertPolicy(
                    min_score_samples=settings.min_score_samples,
                    cooldown_hours=settings.cooldown_hours,
                    resend_min_drop_amount=settings.resend_min_drop_amount,
                    resend_min_drop_percent=settings.resend_min_drop_percent,
                ),
            )
        now = datetime.now(UTC)
        summary = run_flexible_market_scan(
            settings=settings,
            provider=provider,
            today=now.astimezone(BRASILIA_TIMEZONE).date(),
            current_at=now,
            run_repository=run_repository,
            market_repository=market_repository,
            alert_coordinator=alert_coordinator,
        )
    except FlexibleMarketConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except StorageError as error:
        print(f"Storage error: {error}", file=sys.stderr)
        return 1
    except TelegramError as error:
        print(f"Notification error: {error}", file=sys.stderr)
        return 1
    mode = "dry-run" if args.dry_run else "persisted"
    print(f"Flexible-market scan finished: {summary.status.value} ({mode}).")
    print(f"Planned series: {summary.planned_series}")
    print(f"Successful series: {summary.successful_series}")
    print(f"Empty series: {summary.empty_series}")
    print(f"Failed series: {summary.failed_series}")
    print(f"Calendar requests: {summary.calendar_requests}")
    print(f"Verification requests: {summary.verification_requests}")
    print(f"Analyzed series: {summary.analyzed_series}")
    print(f"Alerts sent: {summary.alerts_sent}")
    return 0 if summary.status is RunStatus.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(cli())

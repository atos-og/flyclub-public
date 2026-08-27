from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from flyclub.flexible_market import (
    FlexibleMarketSummary,
    _periods,
    _verify_period,
    cli,
    run_flexible_market_scan,
)
from flyclub.flexible_market_config import FlexibleMarketConfigError, load_flexible_market_text
from flyclub.flexible_market_models import CalendarFare, CalendarSearchOutcome
from flyclub.models import FlightLeg, FlightOption, PriceObservation, SearchOutcome, SearchStatus
from flyclub.storage.postgres import RunStatus

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _settings() -> object:
    return load_flexible_market_text(
        """
markets:
  - id: sample_market
    label: Sample market
    origin_airports: [JFK]
    destination_airports: [LHR, LGW]
    trip_duration_days: 10
    passengers: 1
    cabin: ECONOMY
    currency: USD
    max_stops: ANY
    minimum_days_ahead: 14
    maximum_days_ahead: 305
    score_threshold_2026: 80
    score_threshold_future: 75
verification_candidates_per_period: 2
verification_results: 5
"""
    )


class FakeProvider:
    name = "fake_flexible"

    def __init__(self) -> None:
        self.verifications: list[tuple[date, date]] = []

    def search_calendar(self, _market: object, *, start_date: date, end_date: date) -> object:
        assert start_date == date(2026, 9, 15)
        assert end_date == date(2027, 7, 3)
        return CalendarSearchOutcome(
            provider=self.name,
            status=SearchStatus.SUCCESS,
            fares=(
                CalendarFare(date(2027, 1, 10), date(2027, 1, 20), Decimal("700"), "USD"),
                CalendarFare(date(2026, 11, 10), date(2026, 11, 20), Decimal("800"), "USD"),
            ),
            request_count=5,
        )

    def verify(
        self,
        _market: object,
        *,
        departure_date: date,
        return_date: date,
        max_results: int,
    ) -> SearchOutcome:
        assert max_results == 5
        self.verifications.append((departure_date, return_date))
        price = Decimal("700") if departure_date.year == 2027 else Decimal("800")
        return SearchOutcome(
            provider=self.name,
            status=SearchStatus.SUCCESS,
            options=(
                FlightOption(
                    price=price,
                    currency="USD",
                    legs=(
                        FlightLeg(
                            journey_index=0,
                            origin_airport="JFK",
                            destination_airport="LHR",
                            departure_time=None,
                            arrival_time=None,
                            airline="BA",
                            flight_number="117",
                        ),
                    ),
                    stops=0,
                    duration_minutes=600,
                    google_flights_url="https://www.google.com/travel/flights/booking?tfs=test",
                ),
            ),
        )


class FakeRunRepository:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.started: dict[str, object] | None = None
        self.finished: dict[str, object] | None = None

    def start_run(self, **kwargs: object) -> object:
        self.started = kwargs
        return self.run_id

    def finish_run(self, **kwargs: object) -> None:
        self.finished = kwargs


class FakeMarketRepository:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []
        self.evaluations: list[object] = []

    def record_check(self, **kwargs: object) -> object:
        self.checks.append(kwargs)
        return uuid4()

    def price_history(self, **_kwargs: object) -> tuple[PriceObservation, ...]:
        return tuple(
            PriceObservation(price=Decimal("1000"), observed_at=NOW.replace(day=1 + index))
            for index in range(12)
        )

    def last_sent_alert(self, **_kwargs: object) -> None:
        return None

    def update_evaluation(self, **kwargs: object) -> None:
        self.evaluations.append(kwargs["evaluation"])


class FakeAlertCoordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def handle(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def test_scanner_keeps_2026_and_future_periods_separate_and_verified() -> None:
    provider = FakeProvider()
    run_repository = FakeRunRepository()
    market_repository = FakeMarketRepository()
    alerts = FakeAlertCoordinator()

    summary = run_flexible_market_scan(
        settings=_settings(),
        provider=provider,
        today=date(2026, 9, 1),
        current_at=NOW,
        run_repository=run_repository,
        market_repository=market_repository,
        alert_coordinator=alerts,
    )

    assert summary.status is RunStatus.SUCCESS
    assert summary.planned_series == 2
    assert summary.successful_series == 2
    assert summary.failed_series == 0
    assert summary.calendar_requests == 5
    assert summary.verification_requests == 2
    assert summary.analyzed_series == 2
    assert summary.alerts_sent == 2
    assert {check["period"].minimum_deal_score for check in market_repository.checks} == {
        75,
        80,
    }
    assert len(market_repository.evaluations) == 2
    assert all(
        evaluation.statistics.sample_size == 12 for evaluation in market_repository.evaluations
    )
    assert {call["period"].key for call in alerts.calls} == {"remaining_2026", "from_2027"}
    assert run_repository.started["planned_routes"] == 2
    assert run_repository.finished["status"] is RunStatus.SUCCESS


def test_dry_run_performs_no_persistence_or_alert_delivery() -> None:
    provider = FakeProvider()

    summary = run_flexible_market_scan(
        settings=_settings(),
        provider=provider,
        today=date(2026, 9, 1),
        current_at=NOW,
        run_repository=None,
        market_repository=None,
        alert_coordinator=None,
    )

    assert summary.persisted is False
    assert summary.successful_series == 2
    assert summary.analyzed_series == 0
    assert summary.alerts_sent == 0


def test_unexpected_abort_closes_persisted_run_as_failure() -> None:
    class AbortingProvider(FakeProvider):
        def search_calendar(self, *_args, **_kwargs) -> object:
            raise RuntimeError("private upstream detail")

    run_repository = FakeRunRepository()

    try:
        run_flexible_market_scan(
            settings=_settings(),
            provider=AbortingProvider(),
            today=date(2026, 9, 1),
            current_at=NOW,
            run_repository=run_repository,
            market_repository=FakeMarketRepository(),
            alert_coordinator=None,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected provider exception")

    assert run_repository.finished["status"] is RunStatus.FAILURE
    assert run_repository.finished["failed_routes"] == 2
    assert run_repository.finished["error_code"] == "FLEXIBLE_MARKET_ABORTED"
    assert "private upstream detail" not in run_repository.finished["error_message"]


def test_cli_dry_run_reports_only_aggregate_counts(monkeypatch, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr("flyclub.flexible_market.load_dotenv", lambda *, override: None)
    monkeypatch.setattr(
        "flyclub.flexible_market.load_flexible_market_config", lambda _path: settings
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.GoogleFlightsFlexibleProvider", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.run_flexible_market_scan",
        lambda **_kwargs: FlexibleMarketSummary(RunStatus.SUCCESS, 2, 2, 0, 0, 5, 2, 0, 0, False),
    )

    assert cli(["--config", "private.yaml", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "Planned series: 2" in output
    assert "Calendar requests: 5" in output
    assert "sample_market" not in output


def test_period_planner_uses_only_future_policy_after_2026() -> None:
    market = SimpleNamespace(**_settings().markets[0].model_dump())
    from flyclub.flexible_market_models import market_definition

    periods = _periods(market_definition(market), today=date(2027, 1, 1))

    assert len(periods) == 1
    assert periods[0].key == "from_2027"
    assert periods[0].minimum_deal_score == 75


def test_verification_preserves_failure_when_no_candidate_can_be_confirmed() -> None:
    class FailedProvider:
        name = "failed"

        def verify(self, *_args, **_kwargs) -> SearchOutcome:
            return SearchOutcome(
                self.name,
                SearchStatus.TEMPORARY_FAILURE,
                error_code="TIMEOUT",
                error_message="sanitized",
            )

    fare = CalendarFare(date(2027, 1, 10), date(2027, 1, 20), Decimal("700"), "USD")
    selected, outcome, attempts = _verify_period(
        provider=FailedProvider(),
        market=SimpleNamespace(),
        fares=(fare,),
        candidate_limit=2,
        max_results=5,
    )

    assert selected is None
    assert outcome.status is SearchStatus.TEMPORARY_FAILURE
    assert attempts == 1


def test_cli_persisted_path_constructs_only_the_isolated_dependencies(monkeypatch) -> None:
    settings = _settings()
    captured: dict[str, object] = {}
    run_repository = object()
    market_repository = object()
    telegram = object()
    coordinator = object()
    monkeypatch.setattr("flyclub.flexible_market.load_dotenv", lambda *, override: None)
    monkeypatch.setattr(
        "flyclub.flexible_market.load_flexible_market_config", lambda _path: settings
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.GoogleFlightsFlexibleProvider", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.PostgresRepository",
        SimpleNamespace(from_env=lambda: run_repository),
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.FlexibleMarketRepository",
        SimpleNamespace(from_env=lambda: market_repository),
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.TelegramClient",
        SimpleNamespace(from_env=lambda: telegram),
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.FlexibleMarketAlertCoordinator",
        lambda repository, client, policy: (
            captured.update(
                repository=repository,
                telegram=client,
                policy=policy,
            )
            or coordinator
        ),
    )
    monkeypatch.setattr(
        "flyclub.flexible_market.run_flexible_market_scan",
        lambda **kwargs: (
            captured.update(scan=kwargs)
            or FlexibleMarketSummary(RunStatus.SUCCESS, 2, 2, 0, 0, 5, 2, 2, 0, True)
        ),
    )

    assert cli(["--config", "private.yaml"]) == 0
    assert captured["repository"] is market_repository
    assert captured["telegram"] is telegram
    assert captured["scan"]["run_repository"] is run_repository
    assert captured["scan"]["market_repository"] is market_repository
    assert captured["scan"]["alert_coordinator"] is coordinator


def test_cli_reports_sanitized_configuration_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("flyclub.flexible_market.load_dotenv", lambda *, override: None)
    monkeypatch.setattr(
        "flyclub.flexible_market.load_flexible_market_config",
        lambda _path: (_ for _ in ()).throw(FlexibleMarketConfigError("invalid private config")),
    )

    assert cli(["--config", "private.yaml", "--dry-run"]) == 2
    assert "Configuration error" in capsys.readouterr().err

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from flyclub.config import FlyClubConfig, load_config
from flyclub.models import OriginRole
from flyclub.route_planner import config_fingerprint, plan_routes

EXAMPLE_PATH = Path("config/routes.example.yaml")


def test_planner_expands_origins_times_destinations() -> None:
    routes = plan_routes(load_config(EXAMPLE_PATH))

    assert len(routes) == 6
    assert {(route.origin_group, route.destination) for route in routes} == {
        ("from_bh", "LIS"),
        ("from_bh", "MAD"),
        ("from_bh", "MIA"),
        ("from_sao_paulo", "LIS"),
        ("from_sao_paulo", "MAD"),
        ("from_sao_paulo", "MIA"),
    }


def test_planner_preserves_origin_semantics() -> None:
    routes = plan_routes(load_config(EXAMPLE_PATH))
    sao_paulo = next(
        route
        for route in routes
        if route.origin_group == "from_sao_paulo" and route.destination == "LIS"
    )

    assert sao_paulo.origin_role is OriginRole.POSITIONING
    assert sao_paulo.origin_airports == ("GRU", "VCP", "CGH")
    assert "não incluído" in (sao_paulo.positioning_notice or "")


def test_alert_price_does_not_change_comparable_route_identity() -> None:
    config = load_config(EXAMPLE_PATH)
    raw = deepcopy(config.model_dump(mode="python"))
    raw["destinations"][0]["alert_price"] = Decimal("2800")
    changed = FlyClubConfig.model_validate(raw)

    original_route = plan_routes(config)[0]
    changed_route = plan_routes(changed)[0]

    assert original_route.key == changed_route.key
    assert original_route.alert_price != changed_route.alert_price
    assert config_fingerprint(config) != config_fingerprint(changed)

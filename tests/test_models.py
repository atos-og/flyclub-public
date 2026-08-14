from decimal import Decimal

import pytest

from flyclub.models import FlightOption, SearchOutcome, SearchStatus


def test_success_requires_at_least_one_option() -> None:
    with pytest.raises(ValueError, match="at least one option"):
        SearchOutcome(provider="fake", status=SearchStatus.SUCCESS)


def test_failure_cannot_carry_options() -> None:
    option = FlightOption(price=Decimal("1234.56"), currency="BRL", legs=())

    with pytest.raises(ValueError, match="Only a successful search"):
        SearchOutcome(
            provider="fake",
            status=SearchStatus.TEMPORARY_FAILURE,
            options=(option,),
        )


def test_empty_result_is_distinct_from_failure() -> None:
    result = SearchOutcome(provider="fake", status=SearchStatus.EMPTY)

    assert result.options == ()
    assert result.error_code is None

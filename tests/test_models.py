from decimal import Decimal

import pytest

from flyclub.models import FlightOption, OriginPriceComparison, SearchOutcome, SearchStatus


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


def test_origin_comparison_requires_positive_decimal_reference() -> None:
    comparison = OriginPriceComparison("CNF", Decimal("3200.00"))

    assert comparison.reference_origin == "CNF"
    assert comparison.reference_price == Decimal("3200.00")

    with pytest.raises(TypeError, match="Decimal"):
        OriginPriceComparison("CNF", 3200)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="must not be empty"):
        OriginPriceComparison("  ", Decimal("3200"))

    with pytest.raises(ValueError, match="greater than zero"):
        OriginPriceComparison("CNF", Decimal("0"))

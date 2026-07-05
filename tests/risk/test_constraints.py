from __future__ import annotations

import pytest

from risk.constraints import BUDGET_CAP_EUR, assert_within_budget_cap


def test_within_cap_does_not_raise():
    assert_within_budget_cap(4_999.0)
    assert_within_budget_cap(BUDGET_CAP_EUR)


def test_over_cap_raises():
    with pytest.raises(ValueError, match="supera il budget cap"):
        assert_within_budget_cap(5_000.01)


def test_custom_cap_overrides_default():
    with pytest.raises(ValueError):
        assert_within_budget_cap(1_500.0, cap_eur=1_000.0)
    assert_within_budget_cap(900.0, cap_eur=1_000.0)

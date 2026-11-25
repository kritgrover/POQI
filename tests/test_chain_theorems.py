"""Regression checks for saturated service, regenerative trapping and independent bounds."""

from math import sqrt

import pytest

from scripts.saturated_chain_check import check_case
from scripts.two_slot_lock_probability import cycle_risks, first_passage_bounds


@pytest.mark.parametrize("policy,memory,expected", [
    ("pressure_relaxed", 1, 0), ("pressure_relaxed", 2, 2 / 3),
    ("balancing", 3, 0), ("balancing", 4, 2 / 3),
    ("pressure_relaxed", 9, .9), ("balancing", 11, .9),
])
def test_unit_rate_and_memory_thresholds(policy, memory, expected):
    unit_rate = check_case(memory, policy)["rates_checked"][0]
    assert unit_rate["link_rates"] == [1, 1]
    assert unit_rate["stationary_reward"] == pytest.approx(expected)


def test_two_slot_shift_holds_with_asymmetric_rates_and_an_odd_budget():
    pressure = check_case(3, "pressure_relaxed")["rates_checked"]
    balancing = check_case(5, "balancing")["rates_checked"]
    for a, b in zip(pressure, balancing):
        assert a["link_rates"] == b["link_rates"]
        assert a["stationary_reward"] == pytest.approx(b["stationary_reward"])


@pytest.mark.parametrize("demand,expected", [(0.5, 1.0), (2 / 3, 1.0), (1, 6 * sqrt(2) - 8)])
def test_offered_chain_eventual_risk(demand, expected):
    risks = cycle_risks(1, 1, demand)
    assert risks["saturation"] == pytest.approx(2 / 3)
    assert risks["ever_lock"] == pytest.approx(expected)
    lo, hi = first_passage_bounds(1, 1, demand, 64, risks["busy_extinction"])
    assert lo - 1e-12 <= expected <= hi + 1e-12
    if demand == 1:
        assert hi - lo < 1e-12


def test_asymmetric_lock_risk_respects_link_symmetry_and_rate_units():
    reference = cycle_risks(1, 2, 1.5)["ever_lock"]
    assert 0 < reference < 1
    assert cycle_risks(2, 1, 1.5)["ever_lock"] == pytest.approx(reference)
    assert cycle_risks(10, 20, 15)["ever_lock"] == pytest.approx(reference)
    assert cycle_risks(1e-15, 2e-15, 1.5e-15)["ever_lock"] == pytest.approx(reference)

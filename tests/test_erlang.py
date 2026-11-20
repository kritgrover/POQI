"""Independent finite-sum checks and boundary tests for loss-based sizing."""

from fractions import Fraction
import math

import pytest

from poqi.analysis.erlang import erlang_b, erlang_capacity, mean_capacity


@pytest.mark.parametrize("load,capacity", [(1, 1), (2, 2), (3, 4), (10, 15), (30, 40)])
def test_erlang_recursion_matches_exact_finite_sum(load, capacity):
    terms = [Fraction(load**k, math.factorial(k)) for k in range(capacity + 1)]
    expected = float(terms[-1] / sum(terms))
    assert erlang_b(load, capacity) == pytest.approx(expected, rel=1e-14)


def test_zero_load_and_zero_capacity_conventions():
    assert erlang_b(0, 0) == erlang_b(10, 0) == 1
    assert erlang_b(0, 1) == erlang_b(0, 50) == 0
    assert mean_capacity(0) == 0
    assert erlang_capacity(0, .01) == 1


def test_large_offered_load_does_not_overflow():
    probability = erlang_b(1e308, 1000)
    assert math.isfinite(probability) and 0 <= probability <= 1
    assert erlang_b(1e-300, 1000) == 0


def test_loss_decreases_with_capacity_and_increases_with_load():
    by_capacity = [erlang_b(10, c) for c in range(31)]
    by_load = [erlang_b(a, 10) for a in (0, .1, 1, 10, 100)]
    assert all(a > b for a, b in zip(by_capacity, by_capacity[1:]))
    assert all(a < b for a, b in zip(by_load, by_load[1:]))


@pytest.mark.parametrize("load,target", [(0, .01), (.1, .05), (1, .01), (10, .01), (100, .001)])
def test_inverse_returns_minimal_capacity(load, target):
    slots = erlang_capacity(load, target)
    assert erlang_b(load, slots) <= target
    assert erlang_b(load, slots - 1) > target


def test_mean_sizing_has_no_one_percent_blocking_guarantee():
    assert mean_capacity(2) == 2
    assert mean_capacity(2.01) == 3
    assert erlang_b(2, mean_capacity(2)) == pytest.approx(.4)
    assert erlang_capacity(2, .01) == 7


def test_capacity_guard_fails_without_returning_an_unmet_target():
    with pytest.raises(ValueError, match="not reached"):
        erlang_capacity(10, .01, max_capacity=2)
    with pytest.raises(ValueError, match="not reached"):
        erlang_capacity(0, .01, max_capacity=0)


@pytest.mark.parametrize("load", [-1, True, "1", None, math.nan, math.inf, -math.inf, 10**1000])
def test_invalid_loads_fail(load):
    for function in (lambda: erlang_b(load, 2), lambda: erlang_capacity(load, .01),
                     lambda: mean_capacity(load)):
        with pytest.raises(ValueError, match="offered load"):
            function()


@pytest.mark.parametrize("capacity", [-1, True, 1.5, "2", None, math.nan, math.inf])
def test_invalid_capacities_fail(capacity):
    with pytest.raises(ValueError, match="capacity"):
        erlang_b(2, capacity)
    with pytest.raises(ValueError, match="max_capacity"):
        erlang_capacity(2, .01, max_capacity=capacity)


@pytest.mark.parametrize("target", [0, 1, -1, 2, True, None, math.nan, math.inf])
def test_invalid_targets_fail(target):
    with pytest.raises(ValueError):
        erlang_capacity(2, target)

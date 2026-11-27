from math import isclose, sqrt

from scripts.two_slot_swap_failure import first_passage_bounds, lock_probability


def test_perfect_swaps_recover_the_known_probabilities():
    assert isclose(lock_probability(1, 1, 1.0, 1.0)["ever_lock"], 6 * sqrt(2) - 8, abs_tol=1e-10)
    assert isclose(lock_probability(1, 1, 0.75, 1.0)["ever_lock"], 0.815270647, abs_tol=1e-8)
    assert lock_probability(1, 1, 0.5, 1.0)["ever_lock"] == 1.0


def test_threshold_scales_with_swap_success():
    assert isclose(lock_probability(1, 1, 0.5, 0.9)["threshold"], 0.6)
    assert lock_probability(1, 1, 0.59, 0.9)["ever_lock"] == 1.0
    assert lock_probability(1, 1, 0.61, 0.9)["ever_lock"] < 1.0


def test_swap_failure_lowers_the_lock_risk_above_the_threshold():
    risks = [lock_probability(1, 1, 1.0, success)["ever_lock"] for success in (1.0, 0.9, 0.5)]
    assert risks == sorted(risks, reverse=True)


def test_closed_form_lies_in_the_first_passage_bracket():
    for success in (0.9, 0.5):
        for demand in (0.5, 1.0):
            row = lock_probability(1, 2, demand, success)
            lower, upper = first_passage_bounds(1, 2, demand, success, 200, row["busy_extinction"])
            assert lower - 1e-9 <= row["ever_lock"] <= upper + 1e-9

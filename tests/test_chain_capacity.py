from math import isclose

from scripts.chain_capacity import check_layout_rule, one_repeater_row, recurrent_states, slots_for_fraction


def test_memory_row_is_slack_at_the_true_residence_time():
    row = one_repeater_row(4, "pressure_relaxed")
    assert isclose(row["exact_rate"], 0.8)
    assert isclose(row["mean_center_occupancy"], 1.6)
    assert isclose(row["implied_residence_time"], 1.0)
    assert isclose(row["lp_alpha_at_that_residence"], 1.0, abs_tol=1e-7)
    assert isclose(row["lp_overstates_rate_by"], 0.2, abs_tol=1e-7)


def test_recurrent_state_rule_reproduces_the_stress_test_layouts():
    assert recurrent_states(2, 4, 2, "pressure_oriented") == 5     # 4/5
    assert recurrent_states(2, 6, 2, "pressure_oriented") == 3     # 2/3: more repeater memory, less service
    assert recurrent_states(4, 6, 4, "pressure_oriented") == 7     # 6/7
    assert recurrent_states(2, 3, 2, "pressure_oriented") == 4     # 3/4
    assert recurrent_states(4, 4, 4, "balancing") == 3             # 2/3


def test_rule_agrees_with_the_enumerator_on_small_layouts():
    assert check_layout_rule(largest_end=3, largest_center=6) == 32


def test_ninety_percent_needs_nine_slots_at_one_repeater_and_more_at_two():
    assert slots_for_fraction(2, 0.9) == 9
    assert slots_for_fraction(3, 0.9) > 9

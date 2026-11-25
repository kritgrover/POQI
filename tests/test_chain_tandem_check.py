from fractions import Fraction

from scripts.chain_tandem_check import policy_rate, tandem_rate, tandem_rate_float

ONE = Fraction(1)


def test_one_repeater_is_the_finite_buffer_queue():
    for memory in (2, 3, 5):
        assert tandem_rate(2, memory, [ONE, ONE]) == Fraction(memory, memory + 1)
        assert policy_rate(2, memory, [ONE, ONE])[0] == Fraction(memory, memory + 1)


def test_two_repeaters_at_two_slots_match_exactly_also_with_unequal_rates():
    assert tandem_rate(3, 2, [ONE] * 3) == policy_rate(3, 2, [ONE] * 3)[0] == Fraction(26, 45)
    rates = [ONE, Fraction(2), ONE]
    assert tandem_rate(3, 2, rates) == policy_rate(3, 2, rates)[0] == Fraction(26, 37)


def test_eager_oriented_swapping_equals_the_line_when_end_nodes_never_fill():
    rates = [ONE, Fraction(2), ONE]
    assert policy_rate(3, (9, 3, 3, 9), rates, asap=True)[0] == tandem_rate(3, 3, rates)
    assert policy_rate(4, (8, 2, 2, 2, 8), [ONE] * 4, asap=True)[0] == tandem_rate(4, 2, [ONE] * 4)


def test_uniform_end_nodes_bind_for_odd_budgets_with_two_repeaters():
    assert policy_rate(3, 3, [ONE] * 3, asap=True)[0] < tandem_rate(3, 3, [ONE] * 3)
    assert policy_rate(3, 4, [ONE] * 3, asap=True)[0] == tandem_rate(3, 4, [ONE] * 3)


def test_pressure_policy_is_slightly_below_the_line_beyond_two_slots():
    gap = tandem_rate(3, 4, [ONE] * 3) - policy_rate(3, 4, [ONE] * 3)[0]
    assert 0 < gap < Fraction(1, 100)


def test_balancing_needs_four_slots_per_repeater():
    assert policy_rate(3, 7, [ONE] * 3, policy="balancing")[0] == 0
    assert policy_rate(3, 8, [ONE] * 3, policy="balancing")[0] > 0


def test_float_solver_agrees_with_the_rational_one():
    assert abs(tandem_rate_float(3, 2) - 26 / 45) < 1e-12
    assert abs(tandem_rate_float(4, 3, [1, 2, 3, 1]) - float(tandem_rate(4, 3, [ONE, 2 * ONE, 3 * ONE, ONE]))) < 1e-10

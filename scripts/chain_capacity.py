"""Hard-slot capacity of repeater chains against the average-memory LP.

Three tables.

1. One repeater, uniform budget M: exact saturated rate, mean center occupancy
   and the residence time they imply, next to what the mean-occupancy LP returns
   when given that residence time.
2. One repeater, arbitrary budgets: a closed rule for the number of recurrent
   imbalance states, checked against the simulator-backed transition enumerator.
3. Several repeaters: slots per repeater that a tandem line of finite buffers
   needs for a target fraction of the unlimited-memory rate.
"""

import argparse
from collections import Counter
from fractions import Fraction
import json

import networkx as nx
import numpy as np

from poqi.lp import size_memory, solve_throughput

if __package__:
    from .chain_tandem_check import tandem_rate_float
    from .saturated_chain_check import reachable_transitions
else:
    from chain_tandem_check import tandem_rate_float
    from saturated_chain_check import reachable_transitions


def recurrent_class(memory, policy):
    moves = reachable_transitions(memory, policy)
    graph = nx.DiGraph()
    graph.add_nodes_from(moves)
    for state, options in moves.items():
        graph.add_edges_from((state, target) for target, _ in options)
    closed, = nx.attracting_components(graph)
    return sorted(closed), moves


def one_repeater_row(memory, policy):
    """Exact saturated quantities at unit link rates, and the LP given the implied residence time."""
    closed, moves = recurrent_class({0: memory, 1: memory, 2: memory}, policy)
    index = {state: i for i, state in enumerate(closed)}
    generator = np.zeros((len(closed), len(closed)))
    reward = np.zeros(len(closed))
    for state in closed:
        for target, done in moves[state]:
            generator[index[state], index[target]] += 1
            generator[index[state], index[state]] -= 1
            reward[index[state]] += done
    system = generator.T.copy()
    system[-1] = 1
    rhs = np.zeros(len(closed))
    rhs[-1] = 1
    law = np.linalg.solve(system, rhs)
    rate = float(law @ reward)
    occupancy = float(law @ np.array([left + right for left, right in closed]))
    row = {"memory": memory, "policy": policy, "exact_rate": rate, "mean_center_occupancy": occupancy,
           "occupancy_fraction_of_budget": occupancy / memory}
    if rate > 0:
        # Admitted pairs reach the center at twice the service rate.
        residence = occupancy / (2 * rate)
        graph = nx.path_graph(3)
        nx.set_edge_attributes(graph, 1.0, "generation_capacity")
        lp = solve_throughput(graph, {(0, 2): 1.0}, mean_residence_time=residence, memory_slots=float(memory))
        row.update(implied_residence_time=residence, lp_alpha_at_that_residence=lp.alpha,
                   lp_overstates_rate_by=lp.alpha - rate)
    return row


def recurrent_states(left_end, center, right_end, policy):
    """Number of recurrent imbalance states for end budgets of at least two."""
    a, b = (center + 1) // 2, center // 2
    left, right = min(a, left_end), min(b, right_end)   # most pairs each side can hold
    if policy == "balancing":
        return left + right - 1
    if a == 1 or b == 1:                                # every coexisting input pair is under pressure
        return left + right + 1
    return left + right + 1 - (left < a) - (right < b)   # a side that cannot fill never feels pressure


def check_layout_rule(largest_end=7, largest_center=12):
    checked = 0
    for policy in ("pressure_oriented", "balancing"):
        for left_end in range(2, largest_end + 1):
            for right_end in range(2, largest_end + 1):
                for center in range(2, largest_center + 1):
                    if policy == "balancing" and center < 4:
                        continue
                    closed, moves = recurrent_class({0: left_end, 1: center, 2: right_end}, policy)
                    arrivals = Counter(target for state in closed for target, _ in moves[state])
                    if set(arrivals.values()) != {2}:
                        raise ArithmeticError("stationary law is not uniform at unit rates")
                    exact = Fraction(sum(done for state in closed for _, done in moves[state]), len(closed))
                    states = recurrent_states(left_end, center, right_end, policy)
                    if exact != Fraction(states - 1, states):
                        raise ArithmeticError(f"rule fails at {(left_end, center, right_end), policy}")
                    checked += 1
    return checked


def slots_for_fraction(links, fraction, state_limit=60_000):
    """Smallest capacity reaching the target, by bisection. The rate increases with capacity."""
    largest = int(state_limit ** (1 / (links - 1))) - 1

    def enough(memory):
        # The one-repeater rate M/(M+1) meets round targets exactly; allow rounding error.
        return tandem_rate_float(links, memory) >= fraction - 1e-9

    if not enough(largest):
        return None
    low, high = 0, largest          # enough(high) holds, enough(low) does not
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (low, middle) if enough(middle) else (middle, high)
    return high


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-layouts", action="store_true")
    args = parser.parse_args()
    report = {"one_repeater": [one_repeater_row(memory, policy)
                               for policy in ("pressure_relaxed", "balancing")
                               for memory in (2, 3, 4, 6, 8, 12, 16)]}
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    report["sizing_for_90_percent"] = {
        "lp_mean_budget_at_unit_residence": size_memory(graph, {(0, 2): 1.0}, mean_residence_time=1.0,
                                                        fraction=0.9).memory_budget,
        "exact_slots_pressure": 9, "exact_slots_balancing": 11}
    if not args.skip_layouts:
        report["layouts_checked_against_rule"] = check_layout_rule()
    report["tandem_rate"] = {str(links): {str(memory): tandem_rate_float(links, memory)
                                          for memory in (2, 3, 4, 6, 8, 12)
                                          if (memory + 1) ** (links - 1) <= 60_000}
                             for links in (2, 3, 4, 5, 6)}
    report["slots_per_repeater_for_fraction"] = {
        str(fraction): {str(links): slots_for_fraction(links, fraction) for links in (2, 3, 4, 5)}
        for fraction in (0.8, 0.9, 0.95)}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

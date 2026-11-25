"""Enumerate exact one-attempt SeQUeNCe transitions and check saturated chain rates."""

import argparse
from collections import Counter, deque
import hashlib
import json
from math import isclose
from pathlib import Path

import networkx as nx
import numpy as np

from poqi.simulation import run_simulation


ROOT = Path(__file__).resolve().parents[1]
LINKS = ((0, 1), (1, 2))
RATES = ((1, 1), (1, 2), (2, 1))
POLICIES = ("balancing", "pressure_relaxed")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def one_attempt(graph, memory, policy, state, link):
    # Two pending requests suffice for this single arrival. Verify that a request
    # remains pending and that reconstructing a settled state causes no action.
    result = run_simulation(
        graph, {(0, 2): 1}, memory_slots=memory, swap_policy=policy,
        horizon=2, ticks_per_time_unit=1, initial_pairs=dict(zip(LINKS, state)),
        trace=[{"kind": "request", "endpoints": (0, 2), "time": 0, "count": 2},
               {"kind": "generate", "endpoints": link, "time": 1}],
    )
    swaps = [event for event in result["events"] if event["kind"] == "swap"]
    check(all(event["pivot"] == 1 and event["tick"] == 1 for event in swaps),
          f"unexpected pivot or pre-arrival swap at {memory, policy, state, link}")
    check(result["unserved_requests"] > 0 and result["completed_requests"] == len(swaps),
          "saturated service did not consume exactly the pivot outputs")
    counts = Counter(tuple(pair["endpoints"]) for pair in result["live_pairs"])
    check(set(counts) <= set(LINKS) and all(not pair["parents"] for pair in result["live_pairs"]),
          "post-service inventory contains a virtual or swapped-back pair")
    return (counts[LINKS[0]], counts[LINKS[1]]), result["completed_requests"]


def reachable_transitions(memory, policy):
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    pending = deque([(0, 0)])
    transitions = {}
    while pending:
        state = pending.popleft()
        if state in transitions:
            continue
        transitions[state] = [one_attempt(graph, memory, policy, state, link) for link in LINKS]
        pending.extend(target for target, _ in transitions[state] if target not in transitions)
    return transitions


def stationary_service(states, transitions, rates):
    """Obtain the joint inventory's stationary law without using the imbalance formula."""
    index = {state: i for i, state in enumerate(states)}
    generator = np.zeros((len(states), len(states)))
    reward = np.zeros(len(states))
    for i, state in enumerate(states):
        for rate, (target, completed) in zip(rates, transitions[state]):
            generator[i, index[target]] += rate
            generator[i, i] -= rate
            reward[i] += rate * completed
    equations = generator.T.copy()
    equations[-1] = 1
    rhs = np.zeros(len(states))
    rhs[-1] = 1
    probabilities = np.linalg.solve(equations, rhs)
    check(np.min(probabilities) >= -1e-12 and np.allclose(probabilities @ generator, 0, atol=1e-12),
          "invalid stationary probabilities")
    return float(probabilities @ reward)


def check_case(memory, policy):
    transitions = reachable_transitions(memory, policy)
    graph = nx.DiGraph()
    for state, outcomes in transitions.items():
        graph.add_edges_from((state, target) for target, _ in outcomes)
    closed = list(nx.attracting_components(graph))
    check(len(closed) == 1, f"unexpected recurrent classes at {memory, policy}")
    states = sorted(closed[0])
    left, right = (memory + 1) // 2, memory // 2
    reserve = int(policy == "balancing")
    can_serve = min(left, right) > reserve
    low, high = reserve - right, left - reserve
    if can_serve:
        check(len(states) == high - low + 1, "recurrent inventories do not map one-to-one to imbalance")
        check({l - r for l, r in states} == set(range(low, high + 1)),
              "recurrent imbalance support disagrees with theorem")
        for l, r in states:
            d = l - r
            for step, (target, _) in zip((1, -1), transitions[l, r]):
                check(target[0] - target[1] == max(low, min(high, d + step)),
                      f"imbalance transition disagrees at {memory, policy, (l, r)}")
    else:
        check(all(completed == 0 for outcomes in transitions.values() for _, completed in outcomes),
              "positive service below policy threshold")

    rates_checked = []
    for left_rate, right_rate in RATES:
        predicted = 0.0
        if can_serve:
            # Orient the interval so the geometric weights stay at most one.
            slow, fast = sorted((left_rate, right_rate))
            ratio = slow / fast
            weights = [ratio ** i for i in range(high - low + 1)]
            predicted = slow * sum(weights[:-1]) / sum(weights)
        measured = stationary_service(states, transitions, (left_rate, right_rate))
        check(isclose(measured, predicted, rel_tol=1e-10, abs_tol=1e-12),
              f"stationary reward disagrees at {memory, policy, left_rate, right_rate}")
        rates_checked.append({"link_rates": [left_rate, right_rate],
                              "stationary_reward": measured, "formula": predicted})
    return {"memory": memory, "policy": policy, "reachable_states": len(transitions),
            "recurrent_states": len(states), "one_arrival_transitions": 2 * len(transitions),
            "rates_checked": rates_checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-memory", type=int, default=16)
    parser.add_argument("--output", type=Path, help="optional fresh JSON file")
    args = parser.parse_args()
    if args.max_memory < 1:
        parser.error("--max-memory must be positive")
    cases = [check_case(memory, policy)
             for memory in range(1, args.max_memory + 1) for policy in POLICIES]
    sources = [Path(__file__).resolve(), ROOT / "src/poqi/simulation/inventory.py",
               ROOT / "src/poqi/simulation/sequence_adapter.py"]
    report = {"status": "passed", "max_memory": args.max_memory,
              "source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources},
              "transitions": sum(case["one_arrival_transitions"] for case in cases),
              "stationary_rate_checks": sum(len(case["rates_checked"]) for case in cases),
              "cases": cases}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(f"Verified {report['transitions']} one-arrival transitions and "
          f"{report['stationary_rate_checks']} stationary service rates across {len(cases)} cases.")


if __name__ == "__main__":
    main()

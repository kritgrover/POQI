"""Saturated guarded chains against a tandem line of finite-buffer servers.

Under permanent end-to-end backlog, swapping as soon as possible with the
orientation rule turns a chain of ``n`` links into ``n - 1`` stations in series.
Station ``j`` is repeater ``j``. Its content is the number of stored pairs that
end at the repeater from the left minus the number that start there, shifted to
``0..M``. Link 1 feeds station 1 and is lost when that station is full. Link
``j + 1`` moves one unit from station ``j`` to ``j + 1`` and is blocked when the
source is empty or the destination is full. Link ``n`` empties the last station.

This script solves that line exactly and compares it with the exact stationary
service rate of the repository's ``pressure_oriented`` policy, obtained by
enumerating its saturated inventories with the unmodified policy code.
"""

import argparse
from fractions import Fraction
from itertools import product
import json

import networkx as nx
import numpy as np

if __package__:
    from .dead_state_search import Arm
else:
    from dead_state_search import Arm


def stationary(states, moves, rates, exact_limit=80):
    """Stationary law of a finite chain. ``moves[s]`` lists (rate index, target).

    Rational elimination up to ``exact_limit`` states, floating point beyond it.
    """
    index = {state: i for i, state in enumerate(states)}
    size = len(states)
    exact = size <= exact_limit
    zero = Fraction(0) if exact else 0.0
    rows = [[zero] * size for _ in range(size)]
    for state, options in moves.items():
        for link, target in options:
            rate = rates[link] if exact else float(rates[link])
            rows[index[target]][index[state]] += rate      # transpose of the generator
            rows[index[state]][index[state]] -= rate
    rows[-1] = [Fraction(1) if exact else 1.0] * size       # normalization replaces one balance row
    rhs = [zero] * (size - 1) + [Fraction(1) if exact else 1.0]
    if not exact:
        law = np.linalg.solve(np.array(rows), np.array(rhs))
        return {state: float(law[i]) for state, i in index.items()}
    for column in range(size):
        pivot = next(r for r in range(column, size) if rows[r][column] != 0)
        rows[column], rows[pivot] = rows[pivot], rows[column]
        rhs[column], rhs[pivot] = rhs[pivot], rhs[column]
        scale = rows[column][column]
        rows[column] = [value / scale for value in rows[column]]
        rhs[column] /= scale
        for r in range(size):
            factor = rows[r][column]
            if r != column and factor != 0:
                rows[r] = [value - factor * other for value, other in zip(rows[r], rows[column])]
                rhs[r] -= factor * rhs[column]
    return {state: rhs[i] for state, i in index.items()}


def tandem_rate(links, capacity, rates):
    stations = links - 1
    states = list(product(range(capacity + 1), repeat=stations))
    moves = {}
    exits = {}
    for state in states:
        options = []
        if state[0] < capacity:
            options.append((0, (state[0] + 1,) + state[1:]))
        for j in range(stations - 1):
            if state[j] and state[j + 1] < capacity:
                target = list(state)
                target[j] -= 1
                target[j + 1] += 1
                options.append((j + 1, tuple(target)))
        exits[state] = bool(state[-1])
        if state[-1]:
            options.append((links - 1, state[:-1] + (state[-1] - 1,)))
        moves[state] = options
    law = stationary(states, moves, rates)
    return sum(law[state] for state in states if exits[state]) * rates[-1]


def tandem_rate_float(links, capacity, rates=None):
    """Floating-point solution of the same line with sparse algebra, for larger cases."""
    from scipy.sparse import csr_matrix, lil_matrix
    from scipy.sparse.linalg import spsolve

    stations = links - 1
    rates = [1.0] * links if rates is None else [float(rate) for rate in rates]
    radix = capacity + 1
    size = radix ** stations
    weight = [radix ** (stations - 1 - j) for j in range(stations)]
    generator = lil_matrix((size, size))
    exits = np.zeros(size)
    for index, state in enumerate(product(range(radix), repeat=stations)):
        def move(target, rate):
            generator[index, target] += rate
            generator[index, index] -= rate
        if state[0] < capacity:
            move(index + weight[0], rates[0])
        for j in range(stations - 1):
            if state[j] and state[j + 1] < capacity:
                move(index - weight[j] + weight[j + 1], rates[j + 1])
        if state[-1]:
            move(index - weight[-1], rates[-1])
            exits[index] = rates[-1]
    if size <= 3000:
        system = generator.T.tolil()
        system[size - 1, :] = 1.0
        rhs = np.zeros(size)
        rhs[-1] = 1.0
        return float(spsolve(csr_matrix(system), rhs) @ exits)
    # Direct factorization fills in badly on these lattices. Iterate the uniformized chain.
    step = csr_matrix(generator.T) / (2 * sum(rates))
    law = np.full(size, 1.0 / size)
    previous = -1.0
    for sweep in range(400_000):
        law = law + step @ law
        if sweep % 200 == 0:
            law /= law.sum()
            rate = float(law @ exits)
            if abs(rate - previous) < 1e-11:
                return rate
            previous = rate
    raise ArithmeticError("stationary iteration did not converge")


def policy_rate(links, memory, rates, policy="pressure_oriented", asap=False):
    """Exact saturated service rate from the reachable inventories of the policy code.

    ``asap`` removes the count thresholds and keeps the orientation rule.
    """
    edges = tuple((i, i + 1) for i in range(links))
    arm = Arm(edges, ((0, links),), memory, policy, asap=asap)
    backlog = 10 ** 6
    start = ()
    moves, reward = {}, {}
    frontier = [start]
    while frontier:
        signature = frontier.pop()
        if signature in moves:
            continue
        options, completed = [], []
        for link, edge in enumerate(edges):
            target, _, done = arm.apply(signature, [backlog], ("generate", edge))
            options.append((link, target))
            completed.append(done[0])
            if target not in moves:
                frontier.append(target)
        moves[signature], reward[signature] = options, completed
    graph = nx.DiGraph()
    graph.add_nodes_from(moves)
    for state, options in moves.items():
        graph.add_edges_from((state, target) for _, target in options)
    classes = list(nx.attracting_components(graph))
    if len(classes) != 1:
        raise ArithmeticError("saturated inventory chain has several closed classes")
    closed = sorted(classes[0])
    law = stationary(closed, {state: moves[state] for state in closed}, rates)
    rate = sum(law[state] * rates[link] * reward[state][link]
               for state in closed for link in range(links))
    return rate, len(closed)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    rows = []
    cases = [(2, m, (1, 1)) for m in range(2, 9)] + [(2, 4, (1, 2)), (2, 5, (2, 1))]
    cases += [(3, m, (1, 1, 1)) for m in range(2, 7)] + [(3, 2, (1, 2, 1)), (3, 4, (2, 1, 3))]
    cases += [(4, m, (1, 1, 1, 1)) for m in (2, 3, 4)] + [(5, 2, (1, 1, 1, 1, 1)), (5, 3, (1, 1, 1, 1, 1))]
    for links, memory, rates in cases:
        rates = [Fraction(value) for value in rates]
        line = tandem_rate(links, memory, rates)
        actual, states = policy_rate(links, memory, rates)
        eager, eager_states = policy_rate(links, memory, rates, asap=True)
        exact = all(isinstance(value, Fraction) for value in (line, actual, eager))
        same = (lambda x, y: x == y) if exact else (lambda x, y: abs(float(x) - float(y)) < 1e-10)
        rows.append({"links": links, "memory": memory, "rates": [str(r) for r in rates],
                     "tandem": str(line) if exact else float(line),
                     "asap_oriented": str(eager) if exact else float(eager),
                     "pressure_oriented": str(actual) if exact else float(actual),
                     "comparison": "exact rational" if exact else "floating point",
                     "asap_equals_tandem": same(eager, line),
                     "pressure_equals_tandem": same(actual, line),
                     "pressure_minus_tandem": float(actual) - float(line),
                     "recurrent_inventories": [eager_states, states]})
        print(json.dumps(rows[-1]), flush=True)
    print(json.dumps({"cases": len(rows),
                      "asap_equals_tandem": sum(row["asap_equals_tandem"] for row in rows),
                      "pressure_equals_tandem": sum(row["pressure_equals_tandem"] for row in rows),
                      "largest_pressure_shortfall": min(row["pressure_minus_tandem"] for row in rows)}))


if __name__ == "__main__":
    main()

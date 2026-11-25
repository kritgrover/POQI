"""Two-slot chain lockup when a swap succeeds with probability q.

A failed swap destroys both inputs and produces nothing. One service is then a
geometric number of attempts, each lasting the later of two exponential
generation times, so the saturated rate becomes ``q * mu_2``. The backward
endpoint swap that starts the lockup must itself succeed.

``lock_probability`` is the regenerative closed form. ``first_passage_bounds``
is an independent check: it solves the first-event equations of the inventory
phases with the request queue truncated, which brackets the same probability.
The root simulator has perfect swaps, so at q = 1 the phases are the ones checked
against it in ``two_slot_chain_check``; for q < 1 this script is the model.
"""

import json

import numpy as np
from scipy.optimize import brentq
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


def lock_probability(left, right, demand, success):
    """Threshold, busy-period extinction probability, and probability of ever locking."""
    if not (min(left, right, demand) > 0 and 0 < success <= 1):
        raise ValueError("rates must be positive and success must lie in (0, 1]")
    generation, total = left + right, left + right + demand

    def attempt(t):          # transform of max(Exp(left), Exp(right))
        return left / (left + t) + right / (right + t) - generation / (generation + t)

    def service(t):          # geometric number of independent attempts
        return success * attempt(t) / (1 - (1 - success) * attempt(t))

    threshold = success / (1 / left + 1 / right - 1 / generation)
    extinction = (brentq(lambda z: service(demand * (1 - z)) - z, 0, 1 - 1e-12)
                  if demand > threshold else 1.0)
    s = demand * (1 - extinction)

    def first_service(rate):  # one side already stored, then fresh attempts after a failure
        return rate / (rate + s) * (success + (1 - success) * service(s))

    # One excursion from empty inventory and empty queue, ended by the first failed swap,
    # a cleared busy period, a consumed cache, a wrong-origin pair, or an endless busy period.
    lock = success * attempt(demand) * generation / total * success
    escape = (demand / total * (1 - extinction)
              + left / total * demand / (right + demand) * (1 - first_service(right))
              + right / total * demand / (left + demand) * (1 - first_service(left)))
    return {"threshold": threshold, "busy_extinction": extinction, "ever_lock": lock / (lock + escape)}


def first_passage_bounds(left, right, demand, success, limit, extinction):
    """Probability of reaching a wrong-origin pair before the backlog first reaches ``limit``."""
    states = [(phase, n) for n in range(limit) for phase in "ELR"] + [("V", 0)]
    index = {state: i for i, state in enumerate(states)}
    matrix = lil_matrix((len(states), len(states)))
    rhs = np.zeros(len(states))

    def add(row, rate, target):
        if target == "lock":
            rhs[row] += rate
        elif target is not None:
            matrix[row, index[target]] -= rate

    for (phase, n), row in index.items():
        matrix[row, row] = left + right + demand
        if phase == "V":      # idle end-to-end pair
            add(row, demand, ("E", 0))
            for rate in (left, right):
                add(row, rate * success, "lock")
                add(row, rate * (1 - success), ("E", 0))
            continue
        add(row, demand, (phase, n + 1) if n + 1 < limit else None)
        if phase == "E":
            add(row, left, ("L", n))
            add(row, right, ("R", n))
        else:
            same, other = (left, right) if phase == "L" else (right, left)
            add(row, same, (phase, n))                      # rejected generation
            add(row, other * success, ("V", 0) if n == 0 else ("E", n - 1))
            add(row, other * (1 - success), ("E", n))
    solution = spsolve(matrix.tocsr(), rhs)
    lower = float(solution[index["E", 0]])
    return lower, lower + (1 - lower) * extinction ** (limit - 1)


def main():
    rows = []
    for left, right in ((1, 1), (1, 2)):
        for success in (1.0, 0.9, 0.5):
            for demand in (0.2, 0.5, 0.75, 1.0):
                row = lock_probability(left, right, demand, success)
                lower, upper = first_passage_bounds(left, right, demand, success, 400, row["busy_extinction"])
                if not lower - 1e-9 <= row["ever_lock"] <= upper + 1e-9:
                    raise ArithmeticError("closed form lies outside the first-passage bracket")
                rows.append({"link_rates": [left, right], "swap_success": success, "request_rate": demand,
                             **row, "first_passage_lower": lower, "first_passage_upper": upper})
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()

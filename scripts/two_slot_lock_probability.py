"""Compute eventual lock risk and check it against a finite first-passage system."""

import json

import numpy as np
from scipy.optimize import brentq
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

if __package__:
    from .two_slot_chain_check import predicted_transition
else:
    from two_slot_chain_check import predicted_transition


def cycle_risks(left, right, demand):
    if not all(np.isfinite(value) and value > 0 for value in (left, right, demand)):
        raise ValueError("three positive finite event rates are required")
    # Probabilities depend only on relative rates. Work in units of the fastest
    # event stream so a change of time units cannot change the root tolerance.
    scale = max(left, right, demand)
    left, right, demand = left / scale, right / scale, demand / scale
    if min(left, right, demand) == 0:
        raise ValueError("relative event rates exceed floating-point range")
    generation = left + right
    total = generation + demand
    slow, fast = sorted((left, right))
    threshold = slow / (1 + (slow / fast) * (slow / generation))

    def tail_transform(s):
        return 1 / (left + s) + 1 / (right + s) - 1 / (generation + s)

    # Removing the trivial extinction root z=1 leaves a monotone scalar equation in s.
    survival = (brentq(lambda y: demand * tail_transform(demand * y) - 1, 0, 1)
                if demand > threshold else 0.0)
    extinction = 1 - survival
    s = demand * survival
    # E[exp(-demand*S)] for S=max(Exp(left), Exp(right)), in positive terms.
    cache_first = (left / total * (right / (right + demand))
                   + right / total * (left / (left + demand)))
    lock = cache_first * generation / total
    escape = (demand / total * survival
              + left / total * demand / (right + demand) * s / (right + s)
              + right / total * demand / (left + demand) * s / (left + s))
    return {"saturation": threshold * scale, "busy_extinction": extinction,
            "lock_per_cycle": lock, "escape_per_cycle": escape, "ever_lock": lock / (lock + escape)}


def first_passage_bounds(left, right, demand, limit, extinction):
    """Stop at wrong-origin inventory or first backlog K; solve the first-event equations."""
    if limit < 2:
        raise ValueError("queue limit must be at least two")
    states = [(phase, q) for q in range(limit) for phase in ("empty", "left", "right")]
    states.append(("virtual", 0))
    index = {state: i for i, state in enumerate(states)}
    matrix = lil_matrix((len(states), len(states)), dtype=float)
    rhs = np.zeros(len(states))
    for i, state in enumerate(states):
        matrix[i, i] = left + right + demand
        for event, rate in (("L", left), ("R", right), ("A", demand)):
            target, _ = predicted_transition(state, event)
            if target[0].startswith("poison_"):
                rhs[i] += rate
            elif target[1] < limit:
                matrix[i, index[target]] -= rate
    matrix = matrix.tocsr()
    probabilities = spsolve(matrix, rhs)
    if not np.allclose(matrix @ probabilities, rhs, rtol=1e-10, atol=1e-12):
        raise ArithmeticError("first-passage equations failed the residual check")
    lower = float(probabilities[index["empty", 0]])
    # From backlog K, at least K-1 jobs remain at the first service completion.
    # Any later lock requires the ordinary busy period from those jobs to clear.
    upper = lower + (1 - lower) * extinction ** (limit - 1)
    return lower, upper


def main():
    rows = []
    for left, right in ((1, 1), (1, 2), (2, 1)):
        threshold = 1 / (1 / left + 1 / right - 1 / (left + right))
        for demand in (0.5, threshold, 0.75, 1.0, 1.5):
            risks = cycle_risks(left, right, demand)
            previous = 0
            bounds = []
            for limit in (8, 32, 128):
                lower, upper = first_passage_bounds(left, right, demand, limit, risks["busy_extinction"])
                if (lower < previous - 1e-10 or lower > risks["ever_lock"] + 1e-10
                        or upper < risks["ever_lock"] - 1e-10):
                    raise ArithmeticError("queue truncation disagrees with regenerative probability")
                bounds.append({"stop_at_backlog": limit, "lower": lower, "upper": upper})
                previous = lower
            rows.append({"link_rates": [left, right], "request_rate": demand, **risks,
                         "first_passage_bounds": bounds})
    print(json.dumps(rows, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

"""Erlang-B loss baseline and the corresponding mean-load sizing rule.

The offered load is the offered arrival rate times mean holding time. Erlang-B
describes an M/G/c/c system with independent holding times; coupled endpoint
admission, reservations, and policy-dependent residence need separate checks.
"""

import math
from numbers import Integral, Real


def _load(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("offered load must be finite and nonnegative")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError("offered load must be finite and nonnegative") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError("offered load must be finite and nonnegative")
    return value


def _capacity(value, name="capacity"):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return int(value)


def erlang_b(load, capacity):
    """Return loss probability B(c, a) using the stable Erlang recursion.

    A zero-capacity system rejects every attempted arrival, including the
    zero-load limiting convention B(0, 0)=1. For positive capacity, B(c, 0)=0.
    """
    load, capacity = _load(load), _capacity(capacity)
    blocking = 1.0
    for slots in range(1, capacity + 1):
        numerator = load * blocking
        blocking = numerator / (slots + numerator)
    return blocking


def erlang_capacity(load, target_probability, *, max_capacity=100000):
    """Smallest integer c with B(c, load) <= target, or fail at the guard.

    The target must lie strictly between zero and one. The recursion is advanced
    once per capacity, so inversion is linear rather than repeatedly evaluating
    the full Erlang formula.
    """
    load, maximum = _load(load), _capacity(max_capacity, "max_capacity")
    target = _load(target_probability)
    if not 0 < target < 1:
        raise ValueError("target_probability must be strictly between zero and one")
    blocking = 1.0
    for slots in range(1, maximum + 1):
        numerator = load * blocking
        blocking = numerator / (slots + numerator)
        if blocking <= target:
            return slots
    raise ValueError("blocking target not reached within max_capacity")


def mean_capacity(load):
    """Round offered mean occupancy up; this alone provides no loss guarantee."""
    return math.ceil(_load(load))

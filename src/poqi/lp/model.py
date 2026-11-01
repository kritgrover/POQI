"""Sparse constant-D pair balances and prescribed-residence memory accounting.

Adapted from SeQUeNCe/example/path_oblivious_corrected/lp.py at
1223767054660dbfec1fcb901a4dfaf30be2d028. The default equality balances,
arrival/incidence operators, proportional objective, and sizing model are POQI
extensions. No simulator dependency is required by this module.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from math import isfinite
from numbers import Integral, Real
from time import perf_counter

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix, diags, hstack, vstack


def finite_number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not isfinite(number) or number < 0 or (positive and number == 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{label} must be finite and {qualifier}")
    return number


def canonical_pair(pair, ranks, label="pair"):
    try:
        u, v = pair
        valid = u in ranks and v in ranks and u != v
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError(f"Invalid {label}: {pair!r}")
    return (u, v) if ranks[u] < ranks[v] else (v, u)


def pair_mapping(values, pairs, ranks, label, *, complete=False, positive=False):
    if not isinstance(values, Mapping):
        raise ValueError(f"{label} must be a pair mapping")
    result = {}
    for pair, value in values.items():
        canonical = canonical_pair(pair, ranks, label)
        if canonical in result:
            raise ValueError(f"Duplicate unordered {label}: {pair!r}")
        result[canonical] = finite_number(value, label, positive=positive)
    if complete and set(result) != set(pairs):
        raise ValueError(f"{label} must specify every unordered pair, including virtual pairs")
    return result


def node_mapping(value, nodes, label, *, positive=False):
    if isinstance(value, Mapping):
        if set(value) != set(nodes):
            raise ValueError(f"{label} must specify exactly all graph nodes")
        return {node: finite_number(value[node], label, positive=positive) for node in nodes}
    scalar = finite_number(value, label, positive=positive)
    return dict.fromkeys(nodes, scalar)


@dataclass(frozen=True)
class PairBalanceLP:
    nodes: tuple
    pairs: tuple
    swaps: tuple
    generation_indices: dict
    swap_indices: dict
    capacities: dict
    demands: dict
    residence_times: dict
    memory_slots: dict | None
    memory_shape: dict | None
    distillation_pairs: int
    balance_mode: str
    objective_kind: str
    completion_scale: float
    alpha_index: int | None
    memory_index: int | None
    objective: np.ndarray
    bounds: tuple
    A_eq: object
    b_eq: np.ndarray
    A_ub: object
    b_ub: np.ndarray
    R: object
    H: object
    B: object
    balance_operator: object
    assembly_seconds: float

    @property
    def arrival_operator(self):
        return self.R

    @property
    def node_incidence(self):
        return self.H

    @property
    def memory_matrix(self):
        return self.B


def build_lp(graph, demand_rate, *, mean_residence_time, memory_slots=None,
             distillation_pairs=1, balance_mode="stationary",
             objective="min_generation", completion_scale=1.0,
             memory_shape=None, fixed_memory_budget=None):
    """Build an inspectable sparse LP over generation, swaps, and optionally alpha/m.

    ``None`` explicitly disables memory constraints. Residence times remain
    required, positive coefficients even then, so returned occupancy diagnostics
    retain the same conditional interpretation as the memory-constrained model.
    """
    started = perf_counter()
    if graph.is_directed() or graph.is_multigraph() or any(u == v for u, v in graph.edges()):
        raise ValueError("Use a simple undirected graph without self-loops")
    nodes = tuple(graph.nodes())
    if len(nodes) < 2:
        raise ValueError("At least two graph nodes are required")
    if isinstance(distillation_pairs, bool) or not isinstance(distillation_pairs, Integral) or distillation_pairs < 1:
        raise ValueError("distillation_pairs must be a positive integer")
    if balance_mode not in {"stationary", "legacy"}:
        raise ValueError("balance_mode must be 'stationary' or 'legacy'")
    if objective not in {"min_generation", "throughput", "size_memory"}:
        raise ValueError("Unknown LP objective")
    completion_scale = finite_number(completion_scale, "completion_scale")
    ranks = {node: index for index, node in enumerate(nodes)}
    pairs = tuple(combinations(nodes, 2))
    pair_rows = {pair: index for index, pair in enumerate(pairs)}
    demands = pair_mapping(demand_rate, pairs, ranks, "demand_rate")
    if objective == "throughput" and not any(demands.values()):
        raise ValueError("Proportional throughput requires nonzero demand_rate")
    if isinstance(mean_residence_time, Mapping):
        residence = pair_mapping(mean_residence_time, pairs, ranks, "mean_residence_time", complete=True, positive=True)
    else:
        residence = dict.fromkeys(pairs, finite_number(mean_residence_time, "mean_residence_time", positive=True))
    budgets = None if memory_slots is None else node_mapping(memory_slots, nodes, "memory_slots")
    shape = None
    if objective == "size_memory":
        if memory_slots is not None:
            raise ValueError("Sizing uses memory_shape, not fixed memory_slots")
        shape = node_mapping(1.0 if memory_shape is None else memory_shape, nodes, "memory_shape", positive=True)
    elif memory_shape is not None or fixed_memory_budget is not None:
        raise ValueError("memory_shape/fixed_memory_budget are only valid for sizing")
    capacities = {}
    for pair in pairs:
        if graph.has_edge(*pair):
            attributes = graph[pair[0]][pair[1]]
            if "generation_capacity" not in attributes:
                raise ValueError(f"Missing generation_capacity on edge {pair!r}")
            capacities[pair] = finite_number(attributes["generation_capacity"], "generation_capacity")
        else:
            capacities[pair] = 0.0
    swaps = tuple((pivot, u, v) for pivot in nodes for u, v in pairs if pivot != u and pivot != v)
    generation_indices = {pair: index for index, pair in enumerate(pairs)}
    swap_indices = {swap: len(pairs) + index for index, swap in enumerate(swaps)}
    z_count = len(pairs) + len(swaps)
    r_rows, r_cols, r_values = [], [], []
    e_rows, e_cols, e_values = [], [], []
    for pair, column in generation_indices.items():
        row = pair_rows[pair]
        r_rows.append(row); r_cols.append(column); r_values.append(1.0)
        e_rows.append(row); e_cols.append(column); e_values.append(1.0)
    for (pivot, u, v), column in swap_indices.items():
        output = pair_rows[(u, v)]
        r_rows.append(output); r_cols.append(column); r_values.append(1.0)
        for pair, coefficient in (((u, v), 1.0),
                                  (canonical_pair((pivot, u), ranks), -float(distillation_pairs)),
                                  (canonical_pair((pivot, v), ranks), -float(distillation_pairs))):
            e_rows.append(pair_rows[pair]); e_cols.append(column); e_values.append(coefficient)
    R = coo_matrix((r_values, (r_rows, r_cols)), shape=(len(pairs), z_count)).tocsr()
    E = coo_matrix((e_values, (e_rows, e_cols)), shape=(len(pairs), z_count)).tocsr()
    h_rows, h_cols = [], []
    for column, pair in enumerate(pairs):
        for node in pair:
            h_rows.append(ranks[node]); h_cols.append(column)
    H = coo_matrix((np.ones(len(h_rows)), (h_rows, h_cols)), shape=(len(nodes), len(pairs))).tocsr()
    B = (H @ diags([residence[pair] for pair in pairs]) @ R).tocsr()
    bounds = [(0.0, capacities[pair]) for pair in pairs] + [(0.0, None)] * len(swaps)
    alpha_index = memory_index = None
    demand_vector = distillation_pairs * np.array([demands.get(pair, 0.0) for pair in pairs])
    if objective == "throughput":
        alpha_index = z_count
        balance = hstack((E, csr_matrix(-demand_vector[:, None])), format="csr")
        balance_rhs = np.zeros(len(pairs))
        bounds.append((0.0, 1.0))
    elif objective == "size_memory":
        memory_index = z_count
        balance = hstack((E, csr_matrix((len(pairs), 1))), format="csr")
        balance_rhs = completion_scale * demand_vector
        if fixed_memory_budget is None:
            bounds.append((0.0, None))
        else:
            fixed = finite_number(fixed_memory_budget, "fixed_memory_budget")
            bounds.append((fixed, fixed))
    else:
        balance = E
        balance_rhs = completion_scale * demand_vector
    columns = len(bounds)
    equalities, equality_rhs, inequalities, inequality_rhs = [], [], [], []
    if balance_mode == "stationary":
        equalities.append(balance); equality_rhs.append(balance_rhs)
    else:
        inequalities.append(-balance); inequality_rhs.append(-balance_rhs)
    if objective == "size_memory":
        inequalities.append(hstack((B, csr_matrix(-np.array([shape[node] for node in nodes])[:, None])), format="csr"))
        inequality_rhs.append(np.zeros(len(nodes)))
    elif budgets is not None:
        inequalities.append(hstack((B, csr_matrix((len(nodes), columns - z_count))), format="csr"))
        inequality_rhs.append(np.array([budgets[node] for node in nodes]))
    c = np.zeros(columns)
    if objective == "throughput":
        c[alpha_index] = -1.0
    elif objective == "size_memory" and fixed_memory_budget is None:
        c[memory_index] = 1.0
    else:
        c[:len(pairs)] = 1.0
    return PairBalanceLP(
        nodes, pairs, swaps, generation_indices, swap_indices, capacities,
        demands, residence, budgets, shape, int(distillation_pairs), balance_mode,
        objective, completion_scale, alpha_index, memory_index, c, tuple(bounds),
        vstack(equalities, format="csr") if equalities else csr_matrix((0, columns)),
        np.concatenate(equality_rhs) if equality_rhs else np.empty(0),
        vstack(inequalities, format="csr") if inequalities else csr_matrix((0, columns)),
        np.concatenate(inequality_rhs) if inequality_rhs else np.empty(0),
        R, H, B, E, perf_counter() - started,
    )

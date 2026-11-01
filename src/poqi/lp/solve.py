"""HiGHS solves with independently reconstructed rate and memory residuals."""

from dataclasses import dataclass, field, replace
from time import perf_counter

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import diags

from .model import build_lp, finite_number


@dataclass(frozen=True)
class LPResult:
    success: bool
    status: str
    message: str
    objective: float | None = None
    alpha: float | None = None
    memory_budget: float | None = None
    alpha_infinity: float | None = None
    target_alpha: float | None = None
    demand_cap_reached: bool | None = None
    generation: dict = field(default_factory=dict)
    swaps: dict = field(default_factory=dict)
    completion_rates: dict = field(default_factory=dict)
    pair_arrivals: dict = field(default_factory=dict)
    pair_occupancy: dict = field(default_factory=dict)
    node_occupancy: dict = field(default_factory=dict)
    balance_slack: dict = field(default_factory=dict)
    memory_slack: dict = field(default_factory=dict)
    limiting_nodes: tuple = ()
    residuals: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    balance_mode: str = "stationary"
    objective_kind: str = "min_generation"
    total_generation: float | None = None
    total_completion: float | None = None
    offered_load: float | None = None
    lexicographic: bool = False
    notes: tuple = ()
    numerical_scaling: dict = field(default_factory=dict)

    @property
    def max_constraint_violation(self):
        values = [self.residuals.get(key) for key in ("balance", "memory", "matrix")]
        return max(values) if all(value is not None for value in values) else None

    @property
    def max_bound_violation(self):
        return self.residuals.get("bounds")

    def to_dict(self):
        """JSON-safe records preserve node labels without stringified pair keys."""
        result = {key: getattr(self, key) for key in (
            "success", "status", "message", "objective", "alpha", "memory_budget",
            "alpha_infinity", "target_alpha", "demand_cap_reached", "residuals",
            "timings", "balance_mode", "objective_kind", "total_generation",
            "total_completion", "offered_load", "lexicographic", "notes", "numerical_scaling",
        )}
        for name in ("generation", "completion_rates", "pair_arrivals", "pair_occupancy", "balance_slack"):
            result[name] = [{"pair": list(pair), "value": value} for pair, value in getattr(self, name).items()]
        result["swaps"] = [{"pivot": pivot, "pair": [u, v], "value": value} for (pivot, u, v), value in self.swaps.items()]
        for name in ("node_occupancy", "memory_slack"):
            result[name] = [{"node": node, "value": value} for node, value in getattr(self, name).items()]
        result["limiting_nodes"] = list(self.limiting_nodes)
        result["unallocated_surplus"] = result["balance_slack"] if self.balance_mode == "legacy" else []
        return result


def _scaled_problem(problem):
    """Nondimensionalize rates/memory and equilibrate rows before HiGHS.

    Demand, rather than unused link capacity, sets the useful rate scale. This
    prevents a small workload from disappearing under the solver's absolute
    feasibility threshold. Memory has its own rate*time scale. Independent
    relative residuals below remain necessary for heterogeneous coefficients.
    """
    demand_scale = max(problem.demands.values(), default=0.0)
    rate_scale = demand_scale
    alpha_scale = 1.0
    if problem.alpha_index is not None:
        capacity_scale = max(problem.capacities.values(), default=0.0)
        if capacity_scale > 0 and capacity_scale < rate_scale:
            rate_scale = capacity_scale
            alpha_scale = rate_scale / demand_scale
    else:
        rate_scale *= problem.completion_scale
    if rate_scale == 0:
        rate_scale = max(problem.capacities.values(), default=0.0) or 1.0
    memory_scale = rate_scale * max(problem.residence_times.values())
    if (not np.isfinite(rate_scale) or not np.isfinite(memory_scale)
            or memory_scale <= 0 or alpha_scale <= 0 or not np.isfinite(alpha_scale)):
        raise ValueError("Input scales exceed floating-point range; rescale rates and time units")
    scale = np.full(len(problem.bounds), rate_scale)
    if problem.alpha_index is not None:
        scale[problem.alpha_index] = alpha_scale
    if problem.memory_index is not None:
        scale[problem.memory_index] = memory_scale

    def rows(matrix, rhs):
        transformed = (matrix @ diags(scale)).tocsr()
        magnitude = np.asarray(abs(transformed).max(axis=1).toarray()).ravel() if transformed.shape[0] else np.empty(0)
        magnitude = np.maximum(magnitude, np.abs(rhs))
        magnitude[magnitude == 0] = 1.0
        return (diags(1.0 / magnitude) @ transformed).tocsr(), rhs / magnitude

    A_eq, b_eq = rows(problem.A_eq, problem.b_eq)
    A_ub, b_ub = rows(problem.A_ub, problem.b_ub)
    objective = problem.objective * scale
    objective /= np.max(np.abs(objective)) or 1.0
    bounds = [(lower / factor, None if upper is None else upper / factor)
              for (lower, upper), factor in zip(problem.bounds, scale)]
    return scale, objective, A_eq, b_eq, A_ub, b_ub, bounds, {
        "rate_scale": rate_scale, "memory_scale": memory_scale, "alpha_scale": alpha_scale,
        "residual_interpretation": "dimensionless relative residuals; absolute residuals also reported",
    }


def _relative(violation, *magnitudes):
    magnitude = max((abs(value) for value in magnitudes), default=0.0)
    return violation / magnitude if magnitude else (0.0 if violation == 0 else float("inf"))


def _positive_service_possible(problem):
    """Whether the lossless model admits a strictly positive common rate.

    A finite path of positive generation capacities and positive mean budgets
    supports some positive rate for any finite D and positive finite residence
    coefficients. This is an existence check, not a numerical rate estimate.
    It prevents a solver tolerance from declaring a tiny optimum exactly zero.
    """
    active = {node for node in problem.nodes
              if problem.memory_slots is None or problem.memory_slots[node] > 0}
    neighbors = {node: set() for node in active}
    for (u, v), capacity in problem.capacities.items():
        if capacity > 0 and u in active and v in active:
            neighbors[u].add(v)
            neighbors[v].add(u)
    components = {}
    for node in active:
        if node in components:
            continue
        pending = [node]
        components[node] = node
        while pending:
            current = pending.pop()
            for neighbor in neighbors[current]:
                if neighbor not in components:
                    components[neighbor] = node
                    pending.append(neighbor)
    positive_demands = [pair for pair, rate in problem.demands.items() if rate > 0]
    return bool(positive_demands) and all(
        u in components and v in components and components[u] == components[v]
        for u, v in positive_demands
    )


def solve_problem(problem, *, tolerance=1e-7):
    """Accept optimal status only after dimensionless independent residual checks.

    ``tolerance`` is relative to each balance's own flow and each memory row's
    own occupancy/budget, without an absolute floor that could erase small-unit
    demands. Very ill-conditioned inputs may return numerical_failure rather
    than a scientifically incorrect feasible rate allocation.
    """
    tolerance = finite_number(tolerance, "tolerance", positive=True)
    started = perf_counter()
    scale, objective, A_eq, b_eq, A_ub, b_ub, bounds, numerical_scaling = _scaled_problem(problem)
    raw = linprog(objective,
                  A_ub=A_ub if A_ub.shape[0] else None,
                  b_ub=b_ub if len(b_ub) else None,
                  A_eq=A_eq if A_eq.shape[0] else None,
                  b_eq=b_eq if len(b_eq) else None,
                  bounds=bounds, method="highs")
    timings = {"assembly_seconds": problem.assembly_seconds, "solve_seconds": perf_counter() - started}
    common = {"timings": timings, "balance_mode": problem.balance_mode,
              "objective_kind": problem.objective_kind, "offered_load": sum(problem.demands.values()),
              "numerical_scaling": numerical_scaling}
    if not raw.success:
        status = {1: "iteration_limit", 2: "infeasible", 3: "unbounded", 4: "solver_failure"}.get(raw.status, "solver_failure")
        return LPResult(False, status, str(raw.message), **common)
    values = np.asarray(raw.x, dtype=float)
    if values.shape != problem.objective.shape or not np.all(np.isfinite(values)):
        return LPResult(False, "numerical_failure", "Solver returned nonfinite or malformed variable values", **common)
    values = values * scale
    if not np.all(np.isfinite(values)):
        return LPResult(False, "numerical_failure", "Solver values overflowed the declared rate/memory units", **common)
    generation = {pair: float(values[index]) for pair, index in problem.generation_indices.items()}
    swaps = {swap: float(values[index]) for swap, index in problem.swap_indices.items()}
    alpha = float(values[problem.alpha_index]) if problem.alpha_index is not None else problem.completion_scale
    memory_budget = float(values[problem.memory_index]) if problem.memory_index is not None else None
    completions = {pair: alpha * problem.demands.get(pair, 0.0) for pair in problem.pairs}
    arrivals = dict(generation)
    input_use = dict.fromkeys(problem.pairs, 0.0)
    ranks = {node: i for i, node in enumerate(problem.nodes)}
    def pair(u, v):
        return (u, v) if ranks[u] < ranks[v] else (v, u)
    for (pivot, u, v), rate in swaps.items():
        arrivals[(u, v)] += rate
        input_use[pair(pivot, u)] += rate
        input_use[pair(pivot, v)] += rate
    balance_slack = {p: arrivals[p] - problem.distillation_pairs * (completions[p] + input_use[p]) for p in problem.pairs}
    occupancy = {p: arrivals[p] * problem.residence_times[p] for p in problem.pairs}
    node_occupancy = dict.fromkeys(problem.nodes, 0.0)
    for (u, v), amount in occupancy.items():
        node_occupancy[u] += amount
        node_occupancy[v] += amount
    budgets = problem.memory_slots
    if problem.memory_shape is not None:
        budgets = {node: memory_budget * problem.memory_shape[node] for node in problem.nodes}
    memory_slack = {} if budgets is None else {node: budgets[node] - node_occupancy[node] for node in problem.nodes}
    balance_violation = max((abs(value) if problem.balance_mode == "stationary" else max(0.0, -value) for value in balance_slack.values()), default=0.0)
    relative_balance = max((_relative(abs(slack) if problem.balance_mode == "stationary" else max(0.0, -slack),
                                      arrivals[p], problem.distillation_pairs * (completions[p] + input_use[p]))
                            for p, slack in balance_slack.items()), default=0.0)
    bound_violation = 0.0
    relative_bounds = 0.0
    for value, (lower, upper) in zip(values, problem.bounds):
        bound_violation = max(bound_violation, lower - value, 0.0 if upper is None else value - upper)
        relative_bounds = max(relative_bounds, _relative(max(0.0, lower - value), value, lower))
        if upper is not None:
            relative_bounds = max(relative_bounds, _relative(max(0.0, value - upper), value, upper))
    matrix_violation = max(0.0, float(np.max(np.abs(problem.A_eq @ values - problem.b_eq))) if len(problem.b_eq) else 0.0,
                           float(np.max(problem.A_ub @ values - problem.b_ub)) if len(problem.b_ub) else 0.0)
    residuals = {"balance": balance_violation,
                 "memory": max(0.0, max((-value for value in memory_slack.values()), default=0.0)),
                 "bounds": float(bound_violation), "matrix": matrix_violation,
                 "relative_balance": relative_balance,
                 "relative_memory": max((_relative(max(0.0, -slack), budgets[node], node_occupancy[node])
                                          for node, slack in memory_slack.items()), default=0.0),
                 "relative_bounds": relative_bounds,
                 "tolerance": tolerance}
    relative_matrix = 0.0
    for matrix, rhs, equality in ((problem.A_eq, problem.b_eq, True), (problem.A_ub, problem.b_ub, False)):
        differences = matrix @ values - rhs
        magnitudes = abs(matrix) @ np.abs(values)
        relative_matrix = max(relative_matrix, max((_relative(abs(delta) if equality else max(0.0, delta), magnitude, target)
                                                    for delta, magnitude, target in zip(differences, magnitudes, rhs)), default=0.0))
    residuals["relative_matrix"] = relative_matrix
    valid = all(np.isfinite(value) and value <= tolerance for key, value in residuals.items() if key.startswith("relative_"))
    message = str(raw.message)
    if valid and problem.alpha_index is not None and alpha == 0 and _positive_service_possible(problem):
        valid = False
        message = ("Solver reported zero throughput although positive-capacity paths and positive "
                   "mean budgets imply a strictly positive feasible rate; numerical resolution "
                   "is insufficient for this configuration.")
    objective = alpha if problem.objective_kind == "throughput" else (memory_budget if problem.objective_kind == "size_memory" else sum(generation.values()))
    notes = ("Prescribed-residence conditional average-memory model; no hard-slot feasibility claim.",
             "An optimizer may be nonunique; reported allocations are one solution.")
    if problem.balance_mode == "legacy":
        notes += ("Positive balance slack is unallocated surplus, not stationary inventory or an expiry model.",)
    return LPResult(
        bool(valid), "optimal" if valid else "numerical_failure", message,
        objective=objective, alpha=alpha, memory_budget=memory_budget,
        demand_cap_reached=alpha >= 1.0 - tolerance,
        generation=generation, swaps=swaps, completion_rates=completions,
        pair_arrivals=arrivals, pair_occupancy=occupancy, node_occupancy=node_occupancy,
        balance_slack=balance_slack, memory_slack=memory_slack,
        limiting_nodes=tuple(node for node, slack in memory_slack.items()
                             if _relative(abs(slack), budgets[node], node_occupancy[node]) <= tolerance),
        residuals=residuals, total_generation=sum(generation.values()),
        total_completion=sum(completions.values()), notes=notes, **common,
    )


def solve_min_generation(graph, demand_rate, *, mean_residence_time, memory_slots=None,
                         distillation_pairs=1, balance_mode="stationary", tolerance=1e-7):
    """Minimum admitted generation for specified fixed completion rates."""
    return solve_problem(build_lp(graph, demand_rate, mean_residence_time=mean_residence_time,
                                  memory_slots=memory_slots, distillation_pairs=distillation_pairs,
                                  balance_mode=balance_mode), tolerance=tolerance)


def solve_throughput(graph, demand_rate, *, mean_residence_time, memory_slots=None,
                     distillation_pairs=1, balance_mode="stationary", lexicographic=True,
                     tolerance=1e-7):
    """Maximize 0 <= alpha <= 1 for c[p]=alpha*d[p], optionally minimizing generation."""
    kwargs = dict(mean_residence_time=mean_residence_time, memory_slots=memory_slots,
                  distillation_pairs=distillation_pairs, balance_mode=balance_mode)
    primary = solve_problem(build_lp(graph, demand_rate, objective="throughput", **kwargs), tolerance=tolerance)
    if not primary.success or not lexicographic:
        return primary
    secondary = solve_problem(build_lp(graph, demand_rate, completion_scale=primary.alpha, **kwargs), tolerance=tolerance)
    timings = {key: primary.timings[key] + secondary.timings[key] for key in primary.timings}
    if not secondary.success:
        return replace(secondary, message="Lexicographic generation solve failed: " + secondary.message,
                       objective_kind="throughput", timings=timings)
    return replace(secondary, objective_kind="throughput", objective=primary.alpha,
                   alpha=primary.alpha, lexicographic=True, timings=timings)


def size_memory(graph, demand_rate, *, mean_residence_time, fraction=0.9,
                memory_shape=None, distillation_pairs=1, balance_mode="stationary",
                lexicographic=True, tolerance=1e-7):
    """Reoptimize rates for the smallest m with L[x] <= m*shape[x].

    The target is fraction times the identical memory-unlimited proportional
    optimum. A zero optimum has no informative fraction target and is reported
    as nonserviceable_demand, rather than a misleading zero sizing result.
    """
    fraction = finite_number(fraction, "fraction")
    if fraction > 1:
        raise ValueError("fraction must lie in [0, 1]")
    kwargs = dict(mean_residence_time=mean_residence_time, distillation_pairs=distillation_pairs,
                  balance_mode=balance_mode)
    # Validate the sizing-specific shape even when the unlimited baseline is zero.
    build_lp(graph, demand_rate, objective="size_memory", memory_shape=memory_shape, **kwargs)
    baseline = solve_throughput(graph, demand_rate, lexicographic=lexicographic, tolerance=tolerance, **kwargs)
    if not baseline.success:
        return replace(baseline, objective_kind="size_memory", message="Unlimited-memory baseline failed: " + baseline.message)
    if baseline.alpha <= 0:
        return LPResult(False, "nonserviceable_demand", "The unlimited-memory proportional optimum is zero; a fraction target is uninformative.",
                        alpha_infinity=baseline.alpha, objective_kind="size_memory", balance_mode=balance_mode,
                        offered_load=baseline.offered_load, timings=baseline.timings, notes=baseline.notes)
    target = fraction * baseline.alpha
    problem = build_lp(graph, demand_rate, objective="size_memory", memory_shape=memory_shape,
                       completion_scale=target, **kwargs)
    primary = solve_problem(problem, tolerance=tolerance)
    solution = primary
    accumulated = {key: baseline.timings[key] + primary.timings[key] for key in primary.timings}
    if primary.success and lexicographic:
        secondary = solve_problem(build_lp(graph, demand_rate, objective="size_memory", memory_shape=memory_shape,
                                          completion_scale=target, fixed_memory_budget=primary.memory_budget, **kwargs),
                                  tolerance=tolerance)
        accumulated = {key: accumulated[key] + secondary.timings[key] for key in accumulated}
        solution = replace(secondary, lexicographic=True)
    return replace(solution, alpha_infinity=baseline.alpha, target_alpha=target,
                   demand_cap_reached=baseline.demand_cap_reached, timings=accumulated)

"""Coefficient, memory-accounting, input validation, and residual regression tests."""

from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx
import numpy as np
import pytest

from poqi.lp import build_lp, solve_problem, solve_throughput
from poqi.lp import solve as solver


def chain():
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return graph


def test_arrival_incidence_and_memory_operator_count_virtual_endpoints():
    problem = build_lp(chain(), {(0, 2): 0.1}, mean_residence_time={(0, 1): 2, (0, 2): 3, (1, 2): 5}, distillation_pairs=2)
    column = problem.swap_indices[(1, 0, 2)]
    np.testing.assert_array_equal(problem.R[:, column].toarray().ravel(), [0, 1, 0])
    np.testing.assert_array_equal(problem.B[:, column].toarray().ravel(), [3, 0, 3])
    np.testing.assert_array_equal(problem.balance_operator[:, column].toarray().ravel(), [-2, 1, -2])
    np.testing.assert_array_equal(problem.H.toarray(), [[1, 1, 0], [1, 0, 1], [0, 1, 1]])
    assert problem.R.shape == (3, 6)
    assert problem.B.shape == (3, 6)


def test_chain_mean_budget_one_is_not_one_hard_slot_claim():
    result = solve_throughput(chain(), {(0, 2): 1}, mean_residence_time=1, memory_slots=1)
    assert result.success
    assert result.alpha == pytest.approx(0.5)
    assert result.node_occupancy == pytest.approx({0: 1, 1: 1, 2: 1})
    assert result.limiting_nodes == (0, 1, 2)


def test_reconstruct_heterogeneous_memory_independently():
    tau = {(0, 1): 0.5, (0, 2): 2, (1, 2): 1.5}
    result = solve_throughput(chain(), {(0, 2): 1}, mean_residence_time=tau,
                              memory_slots={0: 3, 1: 5, 2: 2}, distillation_pairs=2)
    assert result.success
    reconstructed = dict.fromkeys(chain().nodes(), 0.0)
    for pair, generated in result.generation.items():
        rate = generated + sum(value for (_, u, v), value in result.swaps.items() if {u, v} == set(pair))
        amount = tau[pair] * rate
        assert result.pair_occupancy[pair] == pytest.approx(amount)
        for node in pair:
            reconstructed[node] += amount
    assert result.node_occupancy == pytest.approx(reconstructed)
    assert sum(result.node_occupancy.values()) == pytest.approx(2 * sum(result.pair_occupancy.values()))


@pytest.mark.parametrize("kwargs", [
    {"mean_residence_time": 0}, {"mean_residence_time": float("nan")},
    {"mean_residence_time": {(0, 1): 1, (1, 2): 1}},
    {"mean_residence_time": {(0, 1): 1, (1, 0): 1, (0, 2): 1, (1, 2): 1}},
    {"memory_slots": {0: 1, 1: 1}}, {"memory_slots": {0: 1, 1: 1, 2: 1, 3: 1}},
    {"memory_slots": -1}, {"memory_slots": float("inf")},
    {"distillation_pairs": True}, {"distillation_pairs": 1.5},
    {"balance_mode": "expiry"},
])
def test_invalid_memory_inputs_fail(kwargs):
    options = {"mean_residence_time": 1, **kwargs}
    with pytest.raises(ValueError):
        build_lp(chain(), {(0, 2): 1}, **options)


@pytest.mark.parametrize("demand", [{(0, 2): -1}, {(0, 2): float("inf")}, {(0, 3): 1},
                                     {(0, 0): 1}, {(0, 2): 1, (2, 0): 1}])
def test_invalid_demands_fail(demand):
    with pytest.raises(ValueError):
        build_lp(chain(), demand, mean_residence_time=1)


def test_graph_and_generation_validation():
    for graph in (nx.DiGraph([(0, 1)]), nx.MultiGraph([(0, 1)]), nx.Graph([(0, 0)])):
        with pytest.raises(ValueError):
            build_lp(graph, {}, mean_residence_time=1)
    graph = chain()
    graph[0][1].pop("generation_capacity")
    with pytest.raises(ValueError, match="generation_capacity"):
        build_lp(graph, {}, mean_residence_time=1)


def test_solver_success_cannot_hide_bad_balance_or_bound():
    problem = build_lp(chain(), {(0, 2): 0.1}, mean_residence_time=1)
    fake = SimpleNamespace(success=True, message="claimed optimal", x=np.zeros(len(problem.bounds)))
    with patch.object(solver, "linprog", return_value=fake):
        result = solve_problem(problem)
    assert not result.success
    assert result.status == "numerical_failure"
    assert result.residuals["balance"] == pytest.approx(0.1)


def test_independent_accounting_catches_corrupted_memory_matrix():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    problem = build_lp(graph, {(0, 1): 0.5}, mean_residence_time=2, memory_slots=0.5)
    problem.A_ub.data[:] = 0  # Matrix check alone now incorrectly permits this value.
    fake = SimpleNamespace(success=True, message="claimed optimal", x=np.array([1.0]))
    with patch.object(solver, "linprog", return_value=fake):
        result = solve_problem(problem)
    assert result.residuals["matrix"] == 0
    assert result.residuals["memory"] == pytest.approx(0.5)
    assert not result.success


def test_legacy_surplus_is_reported_as_unallocated():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 2, "generation_capacity")
    problem = build_lp(graph, {(0, 1): 0.5}, mean_residence_time=1, balance_mode="legacy")
    fake = SimpleNamespace(success=True, message="claimed optimal", x=np.array([2.0]))
    with patch.object(solver, "linprog", return_value=fake):
        result = solve_problem(problem)
    assert result.success
    assert result.balance_slack[(0, 1)] == 0.5
    assert result.to_dict()["unallocated_surplus"][0]["value"] == 0.5


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_solver_values_are_rejected(value):
    problem = build_lp(chain(), {(0, 2): 0.1}, mean_residence_time=1)
    fake = SimpleNamespace(success=True, message="claimed optimal", x=np.full(len(problem.bounds), value))
    with patch.object(solver, "linprog", return_value=fake):
        assert solve_problem(problem).status == "numerical_failure"

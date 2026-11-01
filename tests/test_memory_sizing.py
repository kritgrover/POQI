"""Analytical optima, proportional fairness, sizing shape and tau sensitivity."""

import networkx as nx
import pytest

from poqi.lp import size_memory, solve_throughput
from poqi.lp.analysis import service_memory_lower_bound


def chain():
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return graph


@pytest.mark.parametrize("d,alpha,endpoint,pivot", [(1, 1.0, 1.8, 1.8), (2, 0.25, 1.35, 1.8)])
def test_plan_chain_90_percent_closed_forms(d, alpha, endpoint, pivot):
    result = size_memory(chain(), {(0, 2): 1}, mean_residence_time=1, fraction=0.9, distillation_pairs=d)
    assert result.success
    assert result.alpha_infinity == pytest.approx(alpha)
    assert result.target_alpha == pytest.approx(alpha * 0.9)
    assert result.memory_budget == pytest.approx(1.8)
    assert result.node_occupancy == pytest.approx({0: endpoint, 1: pivot, 2: endpoint})
    assert result.lexicographic


def test_weighted_memory_shape_reoptimizes_budget():
    result = size_memory(chain(), {(0, 2): 1}, mean_residence_time=1, fraction=0.9,
                         memory_shape={0: 2, 1: 1, 2: 2})
    assert result.success
    assert result.memory_budget == pytest.approx(1.8)
    assert result.memory_slack == pytest.approx({0: 1.8, 1: 0, 2: 1.8})


def test_throughput_monotonic_and_bounded_by_matching_unlimited():
    results = [solve_throughput(chain(), {(0, 2): 1}, mean_residence_time=1, memory_slots=budget)
               for budget in (0, 0.5, 1, 2, 4, None)]
    assert all(result.success for result in results)
    assert [result.alpha for result in results] == pytest.approx([0, 0.25, 0.5, 1, 1, 1])


def test_proportional_service_keeps_difficult_pair_in_the_mix():
    result = solve_throughput(chain(), {(0, 1): 1, (0, 2): 1}, mean_residence_time=1)
    assert result.success
    assert result.alpha == pytest.approx(0.5)
    assert result.completion_rates[(0, 1)] == pytest.approx(0.5)
    assert result.completion_rates[(0, 2)] == pytest.approx(0.5)


def test_underloaded_workload_reports_demand_cap():
    result = size_memory(chain(), {(0, 2): 0.1}, mean_residence_time=1, fraction=0.9)
    assert result.success and result.demand_cap_reached
    assert result.alpha_infinity == 1
    assert result.offered_load == 0.1
    assert result.total_completion == pytest.approx(0.09)
    assert result.memory_budget == pytest.approx(0.18)


def test_disconnected_positive_demand_has_undefined_fraction_target():
    graph = chain()
    graph.remove_edge(1, 2)
    unlimited = solve_throughput(graph, {(0, 2): 1}, mean_residence_time=1)
    assert unlimited.success and unlimited.alpha == 0
    result = size_memory(graph, {(0, 2): 1}, mean_residence_time=1)
    assert not result.success
    assert result.status == "nonserviceable_demand"
    assert result.memory_budget is None and result.target_alpha is None


def test_scalar_residence_rescaling_is_exact():
    first = size_memory(chain(), {(0, 2): 1}, mean_residence_time=0.7)
    second = size_memory(chain(), {(0, 2): 1}, mean_residence_time=2.1)
    assert first.success and second.success
    assert second.memory_budget == pytest.approx(3 * first.memory_budget)


def test_componentwise_tau_brackets_and_final_service_bound():
    low = size_memory(chain(), {(0, 2): 1}, mean_residence_time=0.5)
    middle = size_memory(chain(), {(0, 2): 1}, mean_residence_time={(0, 1): 0.5, (0, 2): 1, (1, 2): 2})
    high = size_memory(chain(), {(0, 2): 1}, mean_residence_time=2)
    assert low.memory_budget <= middle.memory_budget <= high.memory_budget
    lower = service_memory_lower_bound(middle, {(0, 1): 0.5, (0, 2): 1, (1, 2): 2})
    assert all(lower[node] <= middle.node_occupancy[node] for node in lower)


def test_sizing_curve_scaling_bound_and_zero_fraction():
    graph = nx.cycle_graph(4)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    budgets = [size_memory(graph, {(0, 2): 2, (1, 3): 1}, mean_residence_time=1, fraction=f).memory_budget
               for f in (0, 0.5, 0.9, 1)]
    assert budgets[0] == 0
    assert budgets == sorted(budgets)
    assert budgets[1] <= 0.5 * budgets[-1] + 1e-8
    assert budgets[2] <= 0.9 * budgets[-1] + 1e-8


def test_sizing_reoptimizes_routes_instead_of_scaling_one_unlimited_solution():
    graph = chain()
    graph.add_edge(0, 2, generation_capacity=0.25)
    # Direct production uses less memory, but cannot supply the whole workload.
    tau = {(0, 1): 0.1, (0, 2): 1, (1, 2): 0.1}
    full = size_memory(graph, {(0, 2): 1}, mean_residence_time=tau, fraction=1)
    half = size_memory(graph, {(0, 2): 1}, mean_residence_time=tau, fraction=0.5)
    assert full.success and half.success
    assert full.memory_budget == pytest.approx(1.075)
    assert half.memory_budget == pytest.approx(0.525)
    assert half.memory_budget < 0.5 * full.memory_budget
    assert half.generation[(0, 2)] == pytest.approx(0.25)


@pytest.mark.parametrize("fraction", [-0.1, 1.1, float("nan"), True])
def test_invalid_fraction(fraction):
    with pytest.raises(ValueError):
        size_memory(chain(), {(0, 2): 1}, mean_residence_time=1, fraction=fraction)


@pytest.mark.parametrize("shape", [{0: 1, 1: 1}, {0: 1, 1: 0, 2: 1}])
def test_incomplete_or_nonpositive_shape(shape):
    with pytest.raises(ValueError):
        size_memory(chain(), {(0, 2): 1}, mean_residence_time=1, memory_shape=shape)


def test_zero_demand_is_not_a_proportional_workload():
    with pytest.raises(ValueError, match="nonzero"):
        solve_throughput(chain(), {}, mean_residence_time=1)


def test_tiny_disconnected_demand_cannot_disappear_into_absolute_tolerance():
    graph = nx.empty_graph(2)
    throughput = solve_throughput(graph, {(0, 1): 1e-9}, mean_residence_time=1)
    sizing = size_memory(graph, {(0, 1): 1e-9}, mean_residence_time=1)
    assert throughput.success and throughput.alpha == 0
    assert sizing.status == "nonserviceable_demand"


def test_tiny_residence_does_not_make_zero_memory_free():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    result = solve_throughput(graph, {(0, 1): 1}, mean_residence_time=1e-10, memory_slots=0)
    assert result.success and result.alpha == 0


def test_limiting_nodes_use_relative_slack_in_declared_units():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    result = solve_throughput(graph, {(0, 1): 1}, mean_residence_time=1e-10, memory_slots=1e-9)
    assert result.success and result.alpha == 1
    assert result.limiting_nodes == ()


def test_tiny_positive_capacity_does_not_become_nonserviceable():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1e-20, "generation_capacity")
    result = size_memory(graph, {(0, 1): 1}, mean_residence_time=1)
    assert result.success
    assert result.alpha_infinity == pytest.approx(1e-20, rel=1e-7, abs=0)
    assert result.memory_budget == pytest.approx(0.9e-20, rel=1e-7, abs=0)


def test_tiny_positive_memory_cannot_be_claimed_to_have_zero_optimum():
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    result = solve_throughput(graph, {(0, 1): 1}, mean_residence_time=1, memory_slots=1e-20)
    # Numerical resolution may be insufficient, but the positive-budget link
    # provably admits a positive rate. Do not label zero as the optimum.
    assert result.status == "numerical_failure" or (
        result.success and result.alpha == pytest.approx(1e-20, rel=1e-7, abs=0)
    )


def test_zero_budget_pivot_really_can_force_zero_throughput():
    result = solve_throughput(chain(), {(0, 2): 1}, mean_residence_time=1,
                              memory_slots={0: 1, 1: 0, 2: 1})
    assert result.success and result.alpha == 0


@pytest.mark.parametrize("rate_factor,time_factor", [(1e-12, 1e12), (1e12, 1e-12), (1, 1e-12), (1e-12, 1)])
def test_common_unit_rescaling_preserves_optimum(rate_factor, time_factor):
    graph = chain()
    nx.set_edge_attributes(graph, rate_factor, "generation_capacity")
    result = solve_throughput(graph, {(0, 2): rate_factor}, mean_residence_time=time_factor,
                              memory_slots=rate_factor * time_factor)
    sizing = size_memory(graph, {(0, 2): rate_factor}, mean_residence_time=time_factor)
    assert result.success and sizing.success
    assert result.alpha == pytest.approx(0.5)
    assert sizing.memory_budget == pytest.approx(1.8 * rate_factor * time_factor, rel=1e-7, abs=0)


def test_heterogeneous_tiny_disconnected_demand_never_returns_false_success():
    graph = nx.Graph()
    graph.add_edge(0, 1, generation_capacity=1)
    graph.add_node(2)
    result = solve_throughput(graph, {(0, 1): 1, (0, 2): 1e-12}, mean_residence_time=1)
    # An ill-conditioned solve may explicitly fail, but may never discard the
    # positive remote component and claim proportional service is possible.
    assert not result.success or result.alpha == 0

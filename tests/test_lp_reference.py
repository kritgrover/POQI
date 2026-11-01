"""Small independent balances and parity with the preserved corrected LP."""

import importlib.util
from pathlib import Path
import sys

import networkx as nx
import pytest

from poqi.lp import solve_min_generation


def chain(capacity=1.0):
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, capacity, "generation_capacity")
    return graph


def reconstruct(result, demand, d):
    assert result.success
    for pair, generated in result.generation.items():
        output = sum(value for (_, u, v), value in result.swaps.items() if {u, v} == set(pair))
        inputs = sum(value for (pivot, u, v), value in result.swaps.items()
                     if set(pair) in ({pivot, u}, {pivot, v}))
        departure = d * (demand.get(pair, demand.get(tuple(reversed(pair)), 0.0)) + inputs)
        assert generated + output == pytest.approx(departure, abs=1e-8)


@pytest.mark.parametrize("d", [1, 2, 3])
def test_direct_link_and_fixed_request_cost(d):
    graph = nx.Graph()
    graph.add_edge("a", "b", generation_capacity=1)
    result = solve_min_generation(graph, {("a", "b"): 0.1}, mean_residence_time=2, distillation_pairs=d)
    assert result.success
    assert result.objective == pytest.approx(0.1 * d)
    assert result.node_occupancy == pytest.approx({"a": 0.2 * d, "b": 0.2 * d})


@pytest.mark.parametrize("d", [1, 2])
def test_chain_virtual_pair_rates(d):
    result = solve_min_generation(chain(), {(0, 2): 0.1}, mean_residence_time=1, distillation_pairs=d)
    reconstruct(result, {(0, 2): 0.1}, d)
    assert result.objective == pytest.approx(2 * d * d * 0.1)
    assert result.swaps[(1, 0, 2)] == pytest.approx(d * 0.1)
    assert result.generation[(0, 2)] == 0


def test_fixed_demand_infeasibility_and_zero_demand():
    assert solve_min_generation(chain(), {(0, 2): 1.01}, mean_residence_time=1).status == "infeasible"
    result = solve_min_generation(chain(), {}, mean_residence_time=1)
    assert result.success and result.objective == 0


@pytest.fixture(scope="module")
def corrected_reference():
    reference = Path(__file__).resolve().parents[1] / "SeQUeNCe/example/path_oblivious_corrected/lp.py"
    spec = importlib.util.spec_from_file_location("poqi_test_corrected_lp_reference", reference)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("factory", [lambda: nx.path_graph(4), lambda: nx.cycle_graph(4), lambda: nx.star_graph(3)])
@pytest.mark.parametrize("d", [1, 2])
def test_legacy_and_stationary_match_preserved_min_generation(corrected_reference, factory, d):
    graph = factory()
    nx.set_edge_attributes(graph, 2.0, "generation_capacity")
    nx.set_edge_attributes(graph, 2.0, "capacity")
    demand = {(0, 3): 0.02, (1, 2): 0.03}
    reference = corrected_reference.solve_lp(graph, demand, distillation_pairs=d)
    assert reference.success
    for mode in ("stationary", "legacy"):
        result = solve_min_generation(graph, demand, mean_residence_time=1, distillation_pairs=d, balance_mode=mode)
        assert result.success
        assert result.objective == pytest.approx(reference.objective)


def test_mixed_node_labels_do_not_require_sorting():
    graph = nx.Graph()
    graph.add_edge("left", (0, 1), generation_capacity=1)
    result = solve_min_generation(graph, {((0, 1), "left"): 0.25}, mean_residence_time=1)
    assert result.success
    assert result.generation[("left", (0, 1))] == 0.25

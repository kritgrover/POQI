"""Memory pressure relaxes the count threshold, not physical feasibility."""

import json
from pathlib import Path

import networkx as nx
import pytest

from poqi.config import parse_config
from poqi.simulation import run_simulation
from poqi.simulation.sequence_adapter import _SequenceSimulation


def network(nodes=3):
    graph = nx.path_graph(nodes)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return graph


def event(time, kind, pair, count=1):
    return {"time": time, "kind": kind, "endpoints": list(pair), "count": count}


def run(trace, *, policy="pressure_relaxed", graph=None, demand=None, **kwargs):
    return run_simulation(network() if graph is None else graph,
                          {(0, 2): 1.0} if demand is None else demand,
                          horizon=8, ticks_per_time_unit=100, trace=trace,
                          swap_policy=policy, **kwargs).to_dict()


def state(graph, memory_slots, *, initial=None, admission="reserved", D=1):
    """Build a valid inventory without invoking automatic policy decisions."""
    return _SequenceSimulation(graph, {}, memory_slots=memory_slots, cutoff_time=None,
                               distillation_pairs=D, horizon=8, seed=0, ticks_per_time_unit=100,
                               time_unit="abstract", swap_policy="pressure_relaxed",
                               admission_policy=admission, request_regime="offered",
                               initial_pairs=initial, trace=[], record_events=True)


@pytest.mark.parametrize("slots,expected", [(1, 0), (2, 1), (3, 1)])
def test_pressure_rule_removes_four_slot_stall_but_not_physical_limit(slots, expected):
    trace = [event(0, "request", (0, 2)), event(1, "generate", (0, 1)),
             event(2, "generate", (1, 2))]
    relaxed = run(trace, memory_slots=slots)
    balancing = run(trace, policy="balancing", memory_slots=slots)
    assert balancing["completed_requests"] == balancing["swaps"] == 0
    assert relaxed["completed_requests"] == relaxed["swaps"] == expected
    assert relaxed["pressure_relaxed_swaps"] == expected
    assert sum(r.get("pressure_relaxed", False) for r in relaxed["events"]) == expected
    assert relaxed["pair_conservation_residual"] == relaxed["occupancy_episode_residual"] == 0
    assert all(row["peak"] <= slots for row in relaxed["occupancy_by_node"])


@pytest.mark.parametrize("D", [1, 2, 3])
@pytest.mark.parametrize("extra,swaps", [(-1, 0), (0, 1), (1, 1)])
def test_empty_output_relaxation_requires_two_D_pivot_slots(D, extra, swaps):
    trace = [event(0, "generate", (0, 1), D), event(1, "generate", (1, 2), D)]
    limits = {0: 2 * D + 2, 1: 2 * D + extra, 2: 2 * D + 2}
    relaxed = run(trace, memory_slots=limits, distillation_pairs=D)
    balancing = run(trace, policy="balancing", memory_slots=limits, distillation_pairs=D)
    assert balancing["swaps"] == 0
    assert relaxed["swaps"] == relaxed["pressure_relaxed_swaps"] == swaps
    assert relaxed["pair_conservation_residual"] == 0


@pytest.mark.parametrize("D", [1, 2, 3])
def test_original_empty_output_boundary_is_not_counted_as_relaxed(D):
    trace = [event(0, "generate", (0, 1), D + 1), event(1, "generate", (1, 2), D + 1)]
    relaxed = run(trace, memory_slots=2 * (D + 1), distillation_pairs=D)
    balancing = run(trace, policy="balancing", memory_slots=2 * (D + 1), distillation_pairs=D)
    assert balancing["swaps"] == relaxed["swaps"] == 1
    assert relaxed["pressure_relaxed_swaps"] == 0
    # The first swap frees pivot slots: a stale full-pressure flag must not persist.
    assert not any(e.get("pressure_relaxed") for e in relaxed["events"])


@pytest.mark.parametrize("left,output,expected", [(1, 1, 0), (2, 1, 1), (2, 2, 0)])
def test_nonempty_output_threshold_relaxes_only_one_count(left, output, expected):
    graph = nx.complete_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    kwargs = dict(graph=graph, admission_policy="tail_drop",
                  memory_slots={0: 20, 1: 2 * left, 2: 20},
                  initial_pairs={(0, 1): left, (1, 2): left, (0, 2): output})
    relaxed = run([event(1, "request", (0, 2))], **kwargs)
    balancing = run([event(1, "request", (0, 2))], policy="balancing", **kwargs)
    assert balancing["swaps"] == 0
    assert relaxed["swaps"] == relaxed["pressure_relaxed_swaps"] == expected


@pytest.mark.parametrize("admission,slots", [("reserved", 4), ("tail_drop", 3)])
def test_no_relaxation_without_full_pivot_or_consumed_origin(admission, slots):
    trace = [event(0, "request", (0, 2)), event(1, "generate", (0, 1)), event(2, "generate", (1, 2))]
    result = run(trace, memory_slots=slots, admission_policy=admission)
    assert result["completed_requests"] == result["pressure_relaxed_swaps"] == 0
    assert result["heuristic_refusals"] > 0


def test_unrelated_full_reservation_does_not_relax_lowest_output_candidate():
    graph = nx.star_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    trace = [event(0, "generate", (0, 1)), event(1, "generate", (0, 2)),
             event(2, "generate", (0, 3), 2)]
    result = run(trace, graph=graph, demand={(1, 2): 1}, memory_slots=6)
    first = next(e for e in result["events"] if e["kind"] == "swap")
    assert first["pivot"] == 0
    assert first["created"][0]["endpoints"] == [1, 3]
    assert first["pressure_relaxed"] is True
    # Candidate (1,2) sorts first, but only origin3 is full; node0 holds4<6 slots.
    before = next(e for e in result["events"] if e["kind"] == "generate" and e["created"][0]["id"] == 3)
    assert next(r["slots"] for r in before["occupancy"] if r["node"] == 0) == 4


def test_pressure_uses_oldest_selected_input_origins_not_all_buffer_origins():
    graph = nx.Graph()
    graph.add_nodes_from(range(6))
    graph.add_edges_from([(0, 1), (0, 2), (0, 3), (1, 4), (2, 4), (3, 5)], generation_capacity=1.0)
    sim = state(graph, {0: 6, 1: 10, 2: 10, 3: 10, 4: 10, 5: 10},
                initial={(0, 1): 1, (1, 4): 1, (0, 2): 2, (2, 4): 1, (0, 3): 1, (3, 5): 1})
    assert sim._swap(1, (0, 4))
    assert sim._swap(2, (0, 4))
    assert sim._swap(3, (0, 5))
    inv = sim.inventory
    assert inv.occupancy[0] == 4 < inv.limits[0]
    assert inv.origin_occupancy[0, 2] == inv.quotas[0][2] == 2
    # The older (0,4) pair uses non-full origin1; a newer one uses full origin2.
    older = inv.oldest((0, 4), 1)[0]
    assert inv.pairs[older].origins[0] == 1
    assert not sim._under_pressure(0, (4, 5))
    inv.remove(older, 0, "expiry")
    assert sim._under_pressure(0, (4, 5))
    inv.validate()


def test_zero_quota_without_consumed_slots_is_not_pressure():
    graph = nx.star_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    sim = state(graph, 2)
    assert sim.inventory.quotas[0][3] == 0
    assert not sim._under_pressure(0, (1, 2))


@pytest.mark.parametrize("cutoff", [None, 5])
def test_unlimited_pressure_rule_exactly_matches_corrected_balancing(cutoff):
    graph = nx.star_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    kwargs = dict(memory_slots=None, horizon=20, seed=4101, cutoff_time=cutoff,
                  ticks_per_time_unit=1000, record_events=True)
    demand = {(1, 2): .5, (1, 3): .5, (2, 3): .5}
    balancing = run_simulation(graph, demand, swap_policy="balancing", **kwargs).to_dict()
    relaxed = run_simulation(graph, demand, swap_policy="pressure_relaxed", **kwargs).to_dict()
    assert relaxed.pop("pressure_relaxed_swaps") == 0
    relaxed["swap_policy"] = "balancing"
    assert relaxed == balancing


def test_relaxed_swap_preserves_inherited_expiry_and_capacity():
    result = run([event(0, "generate", (0, 1)), event(1, "generate", (1, 2)),
                  event(3, "request", (0, 2))], memory_slots=2, cutoff_time=3)
    swap = next(e for e in result["events"] if e["kind"] == "swap")
    assert swap["pressure_relaxed"] is True
    assert swap["created"][0]["deadline_tick"] == 300
    assert result["pressure_relaxed_swaps"] == result["expired_pairs"] == 1
    assert result["completed_requests"] == result["remaining_pairs"] == 0
    assert result["pair_conservation_residual"] == result["occupancy_episode_residual"] == 0


def test_no_expiry_backward_swap_can_leave_full_single_partner_stall():
    """Threshold relaxation alone does not guarantee continued service."""
    trace = [event(1, "generate", (0, 1)), event(2, "generate", (1, 2)),
             event(3, "generate", (1, 2)), event(4, "generate", (0, 1)),
             event(5, "request", (0, 2)), event(6, "generate", (0, 1)),
             event(6, "generate", (1, 2))]
    result = run(trace, memory_slots=2, cutoff_time=None)
    swaps = [e for e in result["events"] if e["kind"] == "swap"]
    assert result["swaps"] == result["pressure_relaxed_swaps"] == 2
    assert [(e["pivot"], e["created"][0]["endpoints"]) for e in swaps] == [
        (1, [0, 2]), (2, [0, 1])]
    # The backward swap retains origin2 at node1, filling that reservation.
    assert {r["node"]: r["neighbor"] for r in swaps[1]["created"][0]["origins"]}[1] == 2
    assert [p["endpoints"] for p in result["live_pairs"]] == [[0, 1], [0, 1]]
    assert all(p["deadline_tick"] is None for p in result["live_pairs"])
    assert result["remaining_pairs"] == 2
    assert result["completed_requests"] == result["expired_pairs"] == 0
    rejected = [e for e in result["events"] if e["kind"] == "reject"]
    assert [(e["time"], e["endpoints"]) for e in rejected] == [(6, [0, 1]), (6, [1, 2])]
    finish = result["events"][-1]
    assert finish["kind"] == "finish" and finish["queue_length"] == 1
    assert next(r["slots"] for r in finish["occupancy"] if r["node"] == 1) == 2
    assert result["pair_conservation_residual"] == result["occupancy_episode_residual"] == 0


def test_pressure_policy_is_accepted_by_configuration():
    path = Path(__file__).resolve().parents[1] / "configs/memory/chain.json"
    data = json.loads(path.read_text())
    data["simulation"]["swap_policy"] = "pressure_relaxed"
    assert parse_config(data).simulation["swap_policy"] == "pressure_relaxed"

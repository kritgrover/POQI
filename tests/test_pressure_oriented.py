"""A D=1 swap must join qubits from distinct physical neighbors of the pivot."""

import json
from pathlib import Path

import networkx as nx
import pytest

from poqi.__main__ import main
from poqi.config import parse_config
from poqi.simulation import run_simulation
from poqi.simulation.sequence_adapter import _SequenceSimulation
from scripts.qcast_concurrent import run_trajectory


CHAIN_CONFIG = Path(__file__).resolve().parents[1] / "configs/memory/chain.json"


def mixed_inventory(paths, *, admission="tail_drop", slots=12):
    """Build virtual 0--partner pairs through physical intermediates, with full lineage."""
    graph = nx.Graph()
    graph.add_nodes_from(range(6))
    graph.add_edges_from([(0, mid) for mid in (1, 2, 3)], generation_capacity=1)
    graph.add_edges_from([(mid, end) for mid in (1, 2, 3) for end in (4, 5)], generation_capacity=1)
    limits = dict.fromkeys(graph, 60)
    limits[0] = slots
    sim = _SequenceSimulation(graph, {}, memory_slots=limits, cutoff_time=None, distillation_pairs=1,
                              horizon=1, seed=0, ticks_per_time_unit=1, time_unit="abstract",
                              swap_policy="pressure_oriented", admission_policy=admission,
                              request_regime="offered", initial_pairs=None, trace=[], record_events=True)
    inventory = sim.inventory
    identifiers = []
    for mid, end, deadline in paths:
        for edge in [(0, mid), (mid, end)]:
            _, reason = inventory.generate(edge, 0, deadline)
            assert reason is None
        pair, _ = inventory.swap(mid, (0, end), 0)
        identifiers.append(pair.identifier)
    return sim, identifiers


@pytest.mark.parametrize("copies", [1, 2])
def test_same_origin_blocks_both_relaxed_and_preferred_branches(copies):
    sim, _ = mixed_inventory([(1, 4, 10), (1, 5, 10)] * copies, slots=2 * copies)
    sim._settle()
    assert sim.counters["swaps"] == 0
    assert not sim._swap(0, (4, 5))
    sim.swap_policy = "pressure_relaxed"
    sim._settle()
    assert sim.events[0]["pivot"] == 0
    assert sim.events[0].get("pressure_relaxed", False) == (copies == 1)


def test_mixed_buffers_choose_first_compatible_ids_in_deadline_order():
    sim, ids = mixed_inventory([(1, 4, 15), (2, 4, 12), (2, 5, 5), (3, 5, 7), (1, 5, 9)])
    sim._settle()
    event = sim.events[0]
    assert event["pivot"] == 0
    assert event["removed"] == [ids[1], ids[3]]
    assert event["created"][0]["parents"] == event["removed"]
    assert event["created"][0]["deadline_tick"] == 7
    assert "pressure_relaxed" not in event


@pytest.mark.parametrize("policy", ["pressure_relaxed", "pressure_oriented"])
def test_later_full_origin_cannot_make_original_partner_pair_eligible(policy):
    sim, _ = mixed_inventory([(1, 4, 10), (3, 5, 6), (2, 5, 7), (2, 5, 9)],
                             admission="reserved", slots=6)
    sim.swap_policy = policy
    # Only origin 2 is full. The original two oldest inputs already differ
    # in origin (1 and 3), and neither releases pressure.
    assert sim.inventory.occupancy[0] == 4
    sim._settle()
    assert sim.counters["swaps"] == 0


def test_relaxed_replacement_retains_pressure_on_selected_input_ids():
    sim, ids = mixed_inventory([(1, 4, 10), (1, 5, 6), (2, 5, 7)],
                               admission="reserved", slots=6)
    assert sim.inventory.occupancy[0] == 3
    # Both original inputs have full origin 1. The new right input uses origin
    # 2, and the retained left input still releases the full origin-1 quota.
    assert sim.inventory.origin_occupancy[0, 1] == sim.inventory.quotas[0][1] == 2
    assert sim.inventory.origin_occupancy[0, 2] < sim.inventory.quotas[0][2]
    sim._settle()
    event = sim.events[0]
    assert event["pressure_relaxed"] is True
    assert event["removed"] == [ids[0], ids[2]]


def test_cli_keeps_cached_endpoint_pair_available_for_request(tmp_path, capsys):
    data = json.loads(CHAIN_CONFIG.read_text())
    data["memory_slots"] = 2
    data["simulation"].update(swap_policy="pressure_oriented", horizon=8, trace=[
        {"kind": "generate", "endpoints": [0, 1], "time": 1},
        {"kind": "generate", "endpoints": [1, 2], "time": 2},
        {"kind": "generate", "endpoints": [0, 1], "time": 3},
        {"kind": "swap", "endpoints": [1, 2], "pivot": 0, "time": 4},
        {"kind": "request", "endpoints": [0, 2], "time": 5},
    ])
    config = tmp_path / "chain.json"
    config.write_text(json.dumps(data))
    assert main(["simulate", "--config", str(config), "--output", str(tmp_path / "run")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["swap_policy"] == "pressure_oriented"
    assert result["swaps"] == result["pressure_relaxed_swaps"] == result["completed_requests"] == 1
    assert result["infeasible_swap_attempts"] == 1
    assert result["pair_conservation_residual"] == 0


def test_d1_scope_is_validated_in_config_and_direct_api():
    data = json.loads(CHAIN_CONFIG.read_text())
    data["simulation"]["swap_policy"] = "pressure_oriented"
    data["distillation_pairs"] = 2
    with pytest.raises(ValueError, match="distillation_pairs=1"):
        parse_config(data)
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    with pytest.raises(ValueError, match="distillation_pairs=1"):
        run_simulation(graph, {}, swap_policy="pressure_oriented", distillation_pairs=2)


@pytest.mark.parametrize("storage", ["Slot", "Persistent", "Cutoff10"])
def test_diamond_runner_accepts_guarded_policy(storage):
    arm = f"POQI-{storage}-pressure_oriented"
    result = run_trajectory("diamond", 2, .5, 7271, arm, 16, None)
    assert result["arm"] == arm
    assert any(row["swaps"] for row in result["slots"])

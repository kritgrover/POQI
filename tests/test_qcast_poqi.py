"""Opportunity scheduling, frozen-rule reuse, and persistence accounting."""

from collections import Counter

import networkx as nx
import pytest

from poqi.simulation.sequence_adapter import _SequenceSimulation
from scripts.qcast_poqi import PoqiOpportunityArm


def graph():
    result = nx.path_graph(3)
    nx.set_edge_attributes(result, 1.0, "generation_capacity")
    return result


CHANNELS = [(0, 1, 0), (0, 1, 1), (1, 2, 2), (1, 2, 3)]


def arm(memory=4, policy="balancing", persistence=True, cutoff=None, **kwargs):
    return PoqiOpportunityArm(graph(), memory, policy, persistence, cutoff, **kwargs)


def slot(model, start, successes=None, channels=CHANNELS):
    allocation = model.begin_slot(start, channels)
    outcome = model.end_slot(start+1, allocation["selected"] if successes is None else successes)
    return allocation, outcome


def test_root_policy_helpers_are_reused_without_reimplementation():
    assert PoqiOpportunityArm._settle is _SequenceSimulation._settle
    assert PoqiOpportunityArm._under_pressure is _SequenceSimulation._under_pressure
    assert PoqiOpportunityArm._swap is _SequenceSimulation._swap


@pytest.mark.parametrize("memory,policy,swaps", [
    (1, "balancing", 0), (2, "balancing", 0), (3, "balancing", 0),
    (4, "balancing", 1), (1, "pressure_relaxed", 0),
    (2, "pressure_relaxed", 1), (3, "pressure_relaxed", 1),
])
def test_batched_policy_thresholds(memory, policy, swaps):
    model = arm(memory, policy)
    allocation, outcome = slot(model, 0)
    assert outcome["swaps"] == swaps
    assert model.ebit_counts().get((0, 2), 0) == swaps
    assert allocation["qubit_time"] == 2 * len(allocation["selected"])
    assert max(allocation["reserved_occupancy"]) <= memory
    model.finish_slot(1)


@pytest.mark.parametrize("policy,memory", [("balancing", 4), ("pressure_relaxed", 2), ("pressure_relaxed", 3)])
def test_batch_settling_matches_actual_root_on_same_initial_inventory(policy, memory):
    model = arm(memory, policy)
    allocation, outcome = slot(model, 0)
    inputs = Counter(tuple(item["pair"]["endpoints"]) for item in outcome["generated"])
    root = _SequenceSimulation(
        graph(), {}, memory_slots=memory, cutoff_time=None, distillation_pairs=1,
        horizon=3, seed=1, ticks_per_time_unit=1, time_unit="slot", swap_policy=policy,
        admission_policy="reserved", request_regime="offered", initial_pairs=inputs,
        trace=[], record_events=True)
    root._settle()
    assert {p: len(ids) for p, ids in root.inventory.buffers.items() if ids} == model.ebit_counts()
    assert root.counters["swaps"] == outcome["swaps"]
    assert root.counters["pressure_relaxed_swaps"] == outcome["pressure_relaxed_swaps"]
    assert [item.origins for item in root.inventory.pairs.values()] == [item.origins for item in model.inventory.pairs.values()]


def test_attempts_reserved_before_failure_outcomes_and_failed_attempts_cost_memory():
    model = arm(2, "balancing")
    allocation = model.begin_slot(0, CHANNELS)
    assert allocation["selected"] == [0, 2]
    assert allocation["reserved_occupancy"] == [1, 2, 1]
    assert allocation["qubit_time"] == 4
    outcome = model.end_slot(1, [])
    assert outcome["generated_pairs"] == outcome["swaps"] == 0
    assert model.counters["failed_attempts"] == 2
    assert not model.inventory.pairs
    model.finish_slot(1)
    assert model.begin_slot(1, CHANNELS)["selected"] == [0, 2]


def test_reservation_order_can_change_selected_channel_but_not_supply_after_reveal():
    forward, reverse = arm(2), arm(2)
    assert forward.begin_slot(0, CHANNELS)["selected"] == [0, 2]
    assert reverse.begin_slot(0, list(reversed(CHANNELS)))["selected"] == [3, 1]
    with pytest.raises(ValueError, match="selected"):
        forward.end_slot(1, [1])
    assert forward.end_slot(1, [0])["generated_pairs"] == 1


def test_no_attempt_reuse_inside_slot_and_origin_quota_blocks_below_total_memory():
    model = arm(3)
    allocation = model.begin_slot(0, CHANNELS)
    assert allocation["selected"] == [0, 1, 2]
    assert allocation["blocked"] == [{"channel": 3, "reason": "hard_slots"}]
    with pytest.raises(ValueError, match="preceding slot"):
        model.begin_slot(0, CHANNELS)
    model.end_slot(1, [2])
    model.finish_slot(1)
    next_allocation = model.begin_slot(1, [(1, 2, 2), (1, 2, 3)])
    assert next_allocation["selected"] == []
    assert all(row["reason"] == "neighbor_reservation" for row in next_allocation["blocked"])
    assert next_allocation["pre_occupancy"] == [0, 1, 1]
    assert next_allocation["qubit_time"] == 2


def test_storage_uses_slots_but_does_not_permanently_own_channel():
    model = arm(4)
    slot(model, 0, successes=[0], channels=[(0, 1, 0)])
    model.finish_slot(1)
    allocation, outcome = slot(model, 1, channels=[(0, 1, 0)])
    assert allocation["selected"] == [0]
    assert allocation["storage_qubit_time"] == 2
    assert allocation["attempt_qubit_time"] == 2
    assert allocation["qubit_time"] == 4
    assert len(outcome["live_pairs"]) == 2


def test_reset_discards_only_unconsumed_inventory():
    model = arm(4, persistence=False)
    _, outcome = slot(model, 0)
    assert outcome["generated_pairs"] == 4 and outcome["swaps"] == 1
    assert model.consume((0, 2), 1)["endpoints"] == [0, 2]
    assert model.consume((0, 2), 1) is None
    final = model.finish_slot(1)
    assert final["discarded_pairs"] == 2
    assert final["consumed_pairs"] == 1
    assert final["remaining_pairs"] == 0
    assert model.begin_slot(1, CHANNELS)["pre_live_pairs"] == 0


def test_persistent_pairs_can_serve_at_next_boundary_before_attempt_planning():
    model = arm(2, "pressure_relaxed")
    slot(model, 0)
    assert model.finish_slot(1)["remaining_pairs"] == 1
    assert model.consume((0, 2), 1)["endpoints"] == [0, 2]
    assert model.begin_slot(1, CHANNELS)["pre_live_pairs"] == 0
    with pytest.raises(ValueError, match="outside an attempt"):
        model.consume((0, 2), 1)


def test_expiry_precedes_batch_settling_and_releases_memory_only_at_end():
    model = arm(2, "pressure_relaxed", cutoff=1)
    slot(model, 0, channels=[(0, 1, 0)])
    model.finish_slot(1)
    allocation, outcome = slot(model, 1, channels=CHANNELS)
    assert allocation["selected"] == [2]
    assert allocation["qubit_time"] == 4
    assert outcome["expired_pairs"] == 1
    assert outcome["swaps"] == 0  # old 01 is unavailable at the boundary
    assert [row["endpoints"] for row in outcome["live_pairs"]] == [[1, 2]]


def test_swapped_pair_inherits_earliest_input_deadline():
    model = arm(2, "pressure_relaxed", cutoff=3)
    slot(model, 0, channels=[(0, 1, 0)])
    model.finish_slot(1)
    _, outcome = slot(model, 1, channels=[(1, 2, 2)])
    assert outcome["swaps"] == 1
    assert outcome["live_pairs"][0]["deadline_tick"] == 4
    model.finish_slot(2)
    slot(model, 2, channels=[])
    model.finish_slot(3)
    _, expired = slot(model, 3, channels=[])
    assert expired["expired_pairs"] == 1
    assert expired["live_pairs"] == []


def test_known_two_slot_no_expiry_single_partner_stall_is_retained():
    model = arm(2, "pressure_relaxed")
    # Same event ordering as root regression, each offered event gets a slot.
    for start, edge in enumerate([(0, 1), (1, 2), (1, 2), (0, 1)]):
        slot(model, start, channels=[(*edge, 0)])
        model.finish_slot(start+1)
    assert model.ebit_counts() == {(0, 1): 2}
    assert model.counters["swaps"] == 2
    assert model.consume((0, 2), 4) is None
    allocation, outcome = slot(model, 4)
    assert allocation["selected"] == []
    assert outcome["swaps"] == 0
    assert model.ebit_counts() == {(0, 1): 2}


@pytest.mark.parametrize("invalid", ["duplicate", "nonphysical", "negative"])
def test_invalid_channel_configuration_does_not_mutate_arm(invalid):
    model = arm()
    channels = {"duplicate": [(0, 1, 0), (1, 2, 0)], "nonphysical": [(0, 2, 0)],
                "negative": [(0, 1, -1)]}[invalid]
    with pytest.raises(ValueError):
        model.begin_slot(0, channels)
    assert model.begin_slot(0, CHANNELS)["selected"] == [0, 1, 2, 3]


@pytest.mark.parametrize("operation", ["end_without_start", "finish_without_end", "wrong_duration", "time_reversal"])
def test_phase_and_time_guards(operation):
    model = arm()
    with pytest.raises(ValueError):
        if operation == "end_without_start":
            model.end_slot(1, [])
        elif operation == "finish_without_end":
            model.begin_slot(0, CHANNELS)
            model.finish_slot(1)
        elif operation == "wrong_duration":
            model.begin_slot(0, CHANNELS)
            model.end_slot(2, [])
        else:
            slot(model, 0)
            model.finish_slot(1)
            model.begin_slot(0, CHANNELS)

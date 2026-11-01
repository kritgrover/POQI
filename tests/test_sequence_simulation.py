"""Deterministic physical accounting and actual SeQUeNCe integration checks."""

from pathlib import Path

import networkx as nx
import pytest

from poqi.simulation import run_simulation


def graph(nodes=3):
    result = nx.path_graph(nodes)
    nx.set_edge_attributes(result, 1.0, "generation_capacity")
    return result


def event(time, kind, endpoints, count=1, **kwargs):
    return {"time": time, "kind": kind, "endpoints": endpoints, "count": count, **kwargs}


def simulate(trace, *, nodes=3, demand=None, **kwargs):
    return run_simulation(graph(nodes), {(0, nodes - 1): 1.0} if demand is None else demand,
                          horizon=kwargs.pop("horizon", 8), ticks_per_time_unit=100,
                          trace=trace, **kwargs).to_dict()


def test_sequence_source_and_timeline_smoke():
    result = simulate([event(1, "generate", [0, 1]), event(2, "request", [0, 1])], nodes=2)
    expected = Path(__file__).resolve().parents[1] / "SeQUeNCe" / "sequence" / "kernel" / "timeline.py"
    assert Path(result["sequence_source"]).resolve() == expected
    assert result["timeline_final_tick"] == 800
    assert result["timeline_run_counter"] == 3
    assert result["completed_requests"] == 1
    assert result["mean_completed_latency"] == 0
    assert [row["integral"] for row in result["occupancy_by_node"]] == [1, 1]


def test_atomic_admission_requires_both_slots():
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [1, 2])],
                      memory_slots={0: 3, 1: 1, 2: 3}, admission_policy="tail_drop")
    assert result["admitted_generation"] == 1
    assert result["admission_rejections"] == 1
    assert [row["final"] for row in result["occupancy_by_node"]] == [1, 1, 0]


@pytest.mark.parametrize("pivot_slots,swaps", [(1, 0), (2, 0), (3, 0), (4, 1)])
def test_balancing_threshold_distinct_from_physical_feasibility(pivot_slots, swaps):
    result = simulate([event(0, "generate", [0, 1], 2), event(1, "generate", [1, 2], 2),
                       event(2, "request", [0, 2])], memory_slots={0: 4, 1: pivot_slots, 2: 4})
    assert result["swaps"] == swaps
    assert result["completed_requests"] == swaps
    if pivot_slots in (2, 3):
        assert result["heuristic_refusals"] > 0


@pytest.mark.parametrize("pivot_slots", [2, 3])
def test_physical_swap_needs_two_pivot_slots_and_reuses_endpoints(pivot_slots):
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [1, 2]),
                       event(2, "request", [0, 2])], memory_slots={0: 1, 1: pivot_slots, 2: 1},
                      swap_policy="physical")
    assert result["swaps"] == 1
    assert result["completed_requests"] == 1
    assert [row["peak"] for row in result["occupancy_by_node"]] == [1, 2, 1]
    assert result["remaining_pairs"] == 0


def test_reservations_prevent_fill_one_input_deadlock():
    trace = [event(0, "generate", [0, 1], 10), event(1, "generate", [1, 2], 2),
             event(2, "request", [0, 2])]
    reserved = simulate(trace, memory_slots=4, admission_policy="reserved")
    tail_drop = simulate(trace, memory_slots=4, admission_policy="tail_drop")
    assert reserved["completed_requests"] == 1
    assert reserved["rejections_by_reason"]["neighbor_reservation"] == 8
    assert tail_drop["completed_requests"] == 0
    assert tail_drop["remaining_pairs"] == 4


def test_swap_inherits_earliest_deadline_and_old_events_are_harmless():
    result = simulate([event(0, "generate", [0, 1]), event(2, "generate", [1, 2]),
                       event(3, "swap", [0, 2], pivot=1), event(4, "generate", [0, 1])],
                      cutoff_time=5, memory_slots=4, swap_policy="none", horizon=8)
    swap = next(row for row in result["events"] if row["kind"] == "swap")
    output = swap["created"][0]
    assert output["admitted_tick"] == 300
    assert output["deadline_tick"] == 500
    assert output["parents"] == [0, 1]
    assert result["expired_pairs"] == 1
    assert result["stale_expiry_events"] == 2
    assert result["remaining_pairs"] == 1
    assert result["live_pairs"][0]["id"] == 3
    assert result["live_pairs"][0]["deadline_tick"] == 900


def test_expiry_precedes_same_time_request_and_generation():
    result = simulate([event(0, "generate", [0, 1]), event(3, "request", [0, 1]),
                       event(3, "generate", [0, 1])], nodes=2, cutoff_time=3,
                      memory_slots=1, horizon=4)
    at_three = [row["kind"] for row in result["events"] if row["tick"] == 300]
    assert at_three == ["expire", "generate", "request", "complete"]
    assert result["admission_rejections"] == 0
    assert result["expired_pairs"] == 1
    assert result["completed_requests"] == 1


def test_boundary_expiry_does_not_trigger_new_policy_actions():
    network = nx.complete_graph(3)
    nx.set_edge_attributes(network, 1.0, "generation_capacity")
    # The older output buffer prevents the corrected balancing predicate from
    # accepting the otherwise ready two-input swap until exactly the horizon.
    trace = [event(0, "generate", [1, 2]), event(1, "generate", [0, 1], 2),
             event(1, "generate", [0, 2], 2)]
    result = run_simulation(network, {(1, 2): 1}, horizon=5, cutoff_time=5,
                            ticks_per_time_unit=100, trace=trace).to_dict()
    assert result["expired_pairs"] == 1
    assert result["swaps"] == 0
    assert result["remaining_pairs"] == 4
    assert [row["final"] for row in result["occupancy_by_node"]] == [4, 2, 2]
    assert [row["kind"] for row in result["events"] if row["tick"] == 500] == ["expire", "finish"]


def test_no_same_time_expired_pair_can_be_swapped():
    result = simulate([event(0, "generate", [0, 1]), event(0, "generate", [1, 2]),
                       event(3, "swap", [0, 2], pivot=1)], swap_policy="none", cutoff_time=3)
    assert result["expired_pairs"] == 2
    assert result["swaps"] == 0
    assert result["infeasible_swap_attempts"] == 1


def test_multihop_swap_never_renews_inherited_deadline():
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [1, 2]),
                       event(2, "generate", [2, 3]), event(3, "swap", [0, 2], pivot=1),
                       event(4, "swap", [0, 3], pivot=2), event(10, "request", [0, 3])],
                      nodes=4, swap_policy="none", cutoff_time=10, horizon=13)
    outputs = [row["created"][0] for row in result["events"] if row["kind"] == "swap"]
    assert [item["deadline_tick"] for item in outputs] == [1000, 1000]
    assert outputs[1]["parents"] == [outputs[0]["id"], 2]
    assert result["swaps"] == 2
    assert result["expired_pairs"] == 1
    assert result["completed_requests"] == 0
    assert result["unserved_requests"] == 1
    assert result["remaining_pairs"] == 0


@pytest.mark.parametrize("options", [
    {"horizon": 1_000_000_000.4, "trace": []},
    {"horizon": 2_000_000_000, "cutoff_time": 1_000_000_000.4, "trace": []},
    {"horizon": 2_000_000_000, "trace": [event(1_000_000_000.4, "generate", [0, 1])]},
])
def test_tick_validation_has_no_relative_tolerance(options):
    with pytest.raises(ValueError, match="integer timeline tick"):
        run_simulation(graph(), {(0, 2): 1}, ticks_per_time_unit=1, **options)


def test_D_accounting_and_slot_release():
    trace = [event(0, "generate", [0, 1], 4), event(1, "generate", [1, 2], 4),
             event(2, "swap", [0, 2], count=2, pivot=1), event(3, "request", [0, 2])]
    result = simulate(trace, distillation_pairs=2, memory_slots=8, swap_policy="none")
    assert result["admitted_generation"] == 8
    assert result["swaps"] == 2
    assert result["completed_requests"] == 1
    assert result["remaining_pairs"] == 8 - 3 * 2 - 2 == 0
    assert [row["peak"] for row in result["occupancy_by_node"]] == [4, 8, 4]


def test_reconstruct_inventory_and_occupancy_from_event_log():
    result = simulate([event(0, "generate", [0, 1], 2), event(1, "generate", [1, 2], 2),
                       event(2, "request", [0, 2]), event(5, "generate", [0, 1])],
                      cutoff_time=4, memory_slots=4)
    live = {}
    occupancy = [0, 0, 0]
    area = [0, 0, 0]
    last_tick = 0
    for row in result["events"]:
        for node in range(3):
            area[node] += occupancy[node] * (row["tick"] - last_tick) / 100
        last_tick = row["tick"]
        for identifier in row.get("removed", []):
            pair = live.pop(identifier)
            for node in pair:
                occupancy[node] -= 1
        for item in row.get("created", []):
            assert item["id"] not in live
            live[item["id"]] = item["endpoints"]
            for node in item["endpoints"]:
                occupancy[node] += 1
        assert occupancy == [item["slots"] for item in row["occupancy"]]
    assert area == pytest.approx([row["integral"] for row in result["occupancy_by_node"]])
    assert result["occupancy_episode_residual"] == 0
    assert sum(area) == pytest.approx(2 * sum(row["departed_residence_sum"] + row["censored_residence_sum"] for row in result["residence_by_pair"]))


def test_initial_inventory_and_censored_residence():
    result = simulate([], nodes=2, initial_pairs={(0, 1): 1}, memory_slots=1)
    assert result["initial_pairs"] == 1
    assert result["remaining_pairs"] == 1
    episode = result["residence_by_pair"][0]
    assert episode["departures"] == 0
    assert episode["completed_episode_mean"] is None
    assert episode["censored_residence_sum"] == 8
    assert episode["window_restricted_mean"] == 8


def test_underload_and_overload_record_unserved_queue():
    supplies = [event(t, "generate", [0, 1]) for t in range(6)]
    underload = simulate(supplies + [event(2.5, "request", [0, 1])], nodes=2)
    overload = simulate(supplies + [event(0, "request", [0, 1], 20)], nodes=2)
    assert underload["completed_requests"] == 1
    assert underload["unserved_requests"] == 0
    assert overload["completed_requests"] == 6
    assert overload["unserved_requests"] == 14
    assert len(overload["unserved_queue"]) == 14
    assert overload["backlog_growth_rate"] == 14 / 8


def test_blocking_global_fifo_is_preserved():
    result = simulate([event(0, "request", [0, 2]), event(1, "generate", [0, 1]),
                       event(2, "request", [0, 1])], demand={(0, 2): 1, (0, 1): 1}, swap_policy="none")
    assert result["completed_requests"] == 0
    assert result["unserved_requests"] == 2
    assert result["remaining_pairs"] == 1


def test_matched_inputs_and_seed_reproducibility():
    kwargs = dict(horizon=20, seed=13, cutoff_time=4, ticks_per_time_unit=100)
    finite = run_simulation(graph(), {(0, 2): 1.0}, memory_slots=4, **kwargs).to_dict()
    repeat = run_simulation(graph(), {(0, 2): 1.0}, memory_slots=4, **kwargs).to_dict()
    unlimited = run_simulation(graph(), {(0, 2): 1.0}, memory_slots=None, **kwargs).to_dict()
    assert finite == repeat
    assert finite["offered_generation"] == unlimited["offered_generation"]
    assert finite["offered_requests"] == unlimited["offered_requests"]
    finite_requests = [(row["tick"], row["endpoints"]) for row in finite["events"] if row["kind"] == "request"]
    unlimited_requests = [(row["tick"], row["endpoints"]) for row in unlimited["events"] if row["kind"] == "request"]
    assert finite_requests == unlimited_requests


@pytest.mark.parametrize("kwargs", [
    {"memory_slots": 1.5}, {"memory_slots": {0: 1, 1: 1}},
    {"cutoff_time": -1}, {"cutoff_time": 0.001}, {"horizon": 0},
    {"ticks_per_time_unit": 0}, {"distillation_pairs": True},
    {"swap_policy": "magic"}, {"admission_policy": "magic"},
    {"request_regime": "stationary"}, {"seed": -1},
    {"initial_pairs": [{"endpoints": [0, 1], "count": 1, "age": 1}]},
])
def test_invalid_simulation_inputs_fail(kwargs):
    options = {"ticks_per_time_unit": 100, "trace": []}
    options.update(kwargs)
    with pytest.raises(ValueError):
        run_simulation(graph(), {(0, 2): 1.0}, **options)


def test_branching_inventory_has_no_cap_violation():
    network = nx.star_graph(3)
    nx.set_edge_attributes(network, 3.0, "generation_capacity")
    result = run_simulation(network, {(1, 2): 1, (1, 3): 1, (2, 3): 1},
                            memory_slots=6, horizon=20, cutoff_time=4, seed=19).to_dict()
    assert all(row["peak"] <= 6 for row in result["occupancy_by_node"])
    assert result["pair_conservation_residual"] == 0
    assert result["occupancy_episode_residual"] == 0

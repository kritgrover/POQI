"""Independent physical-slot lifetimes, capacity exposures and censoring."""

from copy import deepcopy

import networkx as nx
import pytest

from poqi.analysis.blocking import observe_blocking
from poqi.simulation import run_simulation


def simulate(trace, *, nodes=3, **kwargs):
    graph = nx.path_graph(nodes)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return run_simulation(graph, {(0, nodes - 1): 1.0}, trace=trace,
                          horizon=kwargs.pop("horizon", 8), ticks_per_time_unit=100,
                          swap_policy=kwargs.pop("swap_policy", "none"), **kwargs).to_dict()


def event(time, kind, endpoints, **kwargs):
    return {"time": time, "kind": kind, "endpoints": endpoints, **kwargs}


def test_outer_slot_holding_times_survive_swap_episode_reset():
    result = simulate([event(1, "generate", [0, 1]), event(2, "generate", [1, 2]),
                       event(4, "swap", [0, 2], pivot=1), event(7, "request", [0, 2])])
    observed = observe_blocking(result)
    node = {r["node"]: r for r in observed["nodes"]}
    # Physical endpoint residence is 6 and 5, while the output pair episode is 3.
    assert node[0]["completed_holding_mean"] == 6
    assert node[2]["completed_holding_mean"] == 5
    assert node[1]["completed_holding_mean"] == 2.5
    assert [node[n]["cohort_arrivals"] for n in range(3)] == [1, 2, 1]
    assert [node[n]["occupancy_integral"] for n in range(3)] == [6, 5, 5]
    assert all(row["full_run_holding_area_residual"] == 0 for row in observed["nodes"] + observed["origins"])
    pair = next(r for r in result["residence_by_pair"] if r["endpoints"] == [0, 2])
    assert pair["completed_episode_mean"] == 3
    assert observed["completed_requests"] == 1


def test_atomic_remote_rejection_is_not_local_full_exposure():
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [1, 2])],
                       memory_slots={0: 2, 1: 1, 2: 2}, admission_policy="tail_drop")
    observed = observe_blocking(result)
    node = {r["node"]: r for r in observed["nodes"]}
    assert observed["blocking_probability"] == .5
    assert observed["rejections_by_reason"] == {"hard_slots": 1}
    assert node[1]["local_full_probability"] == .5
    assert node[2]["rejected"] == 1
    assert node[2]["local_unavailable_probability"] == 0
    assert node[2]["mean_occupancy"] == 0


def test_neighbor_reservation_blocks_below_total_capacity():
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [0, 1]),
                       event(2, "generate", [0, 1])], memory_slots=4)
    observed = observe_blocking(result)
    pivot = next(r for r in observed["nodes"] if r["node"] == 1)
    origin = next(r for r in observed["origins"] if r["node"] == 1 and r["neighbor"] == 0)
    assert observed["rejections_by_reason"] == {"neighbor_reservation": 1}
    assert pivot["local_full_probability"] == 0
    assert pivot["local_reservation_probability"] == pytest.approx(1 / 3)
    assert pivot["full_time_fraction"] == 0
    assert origin["quota"] == 2
    assert origin["full_time_fraction"] == 7 / 8


def test_warmup_and_arrival_cohort_avoid_left_truncated_holding_means():
    result = simulate([event(0, "generate", [0, 1]), event(2, "generate", [0, 1]),
                       event(4, "generate", [0, 1]), event(6, "generate", [0, 1])],
                      nodes=2, cutoff_time=4)
    observed = observe_blocking(result, warmup=2, cohort_end=4)
    node = observed["nodes"][0]
    # [2,4) cohort contains only the pair born at 2 and expiring at 6.
    assert node["cohort_arrivals"] == node["cohort_departures"] == 1
    assert node["cohort_censored"] == 0
    assert node["cohort_restricted_mean"] == node["completed_holding_mean"] == 4
    assert observed["offered"] == 3
    assert node["offered_rate"] == .5
    assert node["mean_occupancy"] == 2
    assert node["occupancy_distribution"] == [{"slots": 2, "time": 6, "fraction": 1}]


def test_survivors_keep_observed_exposure_and_completed_mean_is_undefined():
    observed = observe_blocking(simulate([event(1, "generate", [0, 1]),
                                          event(3, "generate", [0, 1])], nodes=2))
    node = observed["nodes"][0]
    assert node["cohort_censored"] == node["cohort_arrivals"] == 2
    assert node["cohort_departures"] == 0
    assert node["cohort_censored_holding_sum"] == 12
    assert node["cohort_restricted_mean"] == 6
    assert node["completed_holding_mean"] is None
    assert node["mean_occupancy"] == 1.5


def test_swap_survivors_remain_censored_at_original_slot_admission():
    observed = observe_blocking(simulate([event(1, "generate", [0, 1]),
                                          event(2, "generate", [1, 2]),
                                          event(4, "swap", [0, 2], pivot=1)]))
    node = {r["node"]: r for r in observed["nodes"]}
    assert node[0]["cohort_censored_holding_sum"] == 7
    assert node[2]["cohort_censored_holding_sum"] == 6
    assert node[1]["cohort_censored"] == 0


def test_original_generation_neighbor_and_age_survive_multiple_swaps():
    result = simulate([event(1, "generate", [0, 1]), event(2, "generate", [1, 2]),
                       event(3, "swap", [0, 2], pivot=1), event(4, "generate", [2, 3]),
                       event(5, "swap", [0, 3], pivot=2), event(7, "request", [0, 3])], nodes=4)
    observed = observe_blocking(result)
    origin = next(r for r in observed["origins"] if r["node"] == 0)
    assert origin["neighbor"] == 1
    assert origin["cohort_arrivals"] == 1
    assert origin["completed_holding_mean"] == 6
    assert origin["occupancy_integral"] == 6


def test_expiry_after_swap_uses_physical_slot_ages():
    result = simulate([event(1, "generate", [0, 1]), event(2, "generate", [1, 2]),
                       event(4, "swap", [0, 2], pivot=1)], cutoff_time=5)
    observed = observe_blocking(result)
    node = {r["node"]: r for r in observed["nodes"]}
    assert node[0]["completed_holding_mean"] == 5
    assert node[2]["completed_holding_mean"] == 4
    assert all(r["cohort_censored"] == 0 for r in observed["nodes"])


def test_simultaneous_events_have_zero_intermediate_occupancy_duration():
    observed = observe_blocking(simulate([event(1, "generate", [0, 1]),
                                          event(1, "request", [0, 1])], nodes=2))
    node = observed["nodes"][0]
    assert node["cohort_departures"] == 1
    assert node["completed_holding_mean"] == 0
    assert node["occupancy_distribution"] == [{"slots": 0, "time": 8, "fraction": 1}]


def test_input_signature_is_independent_of_capacity_and_swapping():
    trace = [event(1, "generate", [0, 1]), event(2, "generate", [1, 2]),
             event(3, "request", [0, 2])]
    a = observe_blocking(simulate(trace, memory_slots=1))
    b = observe_blocking(simulate(trace, swap_policy="physical"))
    assert a["exogenous_signature"] == b["exogenous_signature"]
    assert a["accepted"] != b["accepted"]
    assert a["throughput"] == 0 < b["throughput"]


@pytest.mark.parametrize("kwargs", [{"warmup": -1}, {"warmup": 8}, {"warmup": 1.001},
                                     {"cohort_end": 9}, {"warmup": 3, "cohort_end": 2},
                                     {"cohort_end": float("nan")}])
def test_invalid_windows_are_rejected(kwargs):
    with pytest.raises(ValueError, match="window|ticks"):
        observe_blocking(simulate([], nodes=2), **kwargs)


@pytest.mark.parametrize("field,value,match", [("status", "failed", "completed"),
                                               ("distillation_pairs", 2, "D=1"),
                                               ("initial_pairs", 1, "initial"),
                                               ("events", [], "event log")])
def test_incompatible_or_unmeasured_run_is_rejected(field, value, match):
    result = simulate([], nodes=2)
    result[field] = value
    with pytest.raises(ValueError, match=match):
        observe_blocking(result)


@pytest.mark.parametrize("corruption", ["missing", "negative_tick", "occupancy", "total", "integral", "origin"])
def test_corrupt_saved_event_logs_are_rejected(corruption):
    result = deepcopy(simulate([event(1, "generate", [0, 1])], nodes=2))
    if corruption == "missing":
        result["events"].pop(0)
    elif corruption == "negative_tick":
        result["events"][0]["tick"] = -1
    elif corruption == "occupancy":
        result["events"][0]["occupancy"][0]["slots"] = 0
    elif corruption == "total":
        result["offered_generation"] += 1
    elif corruption == "integral":
        result["occupancy_by_node"][0]["integral"] += 1
    else:
        result["events"][0]["created"][0]["origins"][0]["neighbor"] = 0
    with pytest.raises(ValueError):
        observe_blocking(result)


def test_optional_capacity_histogram_preserves_existing_outputs():
    result = simulate([event(1, "generate", [0, 1]), event(2, "generate", [0, 1])], nodes=2)
    old = observe_blocking(result)
    new = observe_blocking(result, physical_neighbors={0: [1], 1: [0]})
    assert new.pop("required_capacity_histogram") == [{"capacity": 1, "attempts": 1},
                                                       {"capacity": 2, "attempts": 1}]
    assert old == new
    assert "required_capacity_histogram" not in old


def test_capacity_histogram_uses_pre_arrival_counts_and_includes_rejections():
    result = simulate([event(1, "generate", [0, 1], count=4)], nodes=2, memory_slots=2)
    observed = observe_blocking(result, physical_neighbors={0: [1], 1: [0]})
    assert observed["required_capacity_histogram"] == [
        {"capacity": 1, "attempts": 1}, {"capacity": 2, "attempts": 1}, {"capacity": 3, "attempts": 2}]
    assert sum(row["attempts"] for row in observed["required_capacity_histogram"]) == observed["offered"] == 4
    assert observed["rejected"] == 2


def test_capacity_histogram_encodes_neighbor_rank_and_reservation_pressure():
    # At node 1, neighbor 2 has rank 1: its first pair requires c=2; its
    # second requires c=4 despite total pivot occupancy only being one.
    result = simulate([event(1, "generate", [1, 2]), event(2, "generate", [1, 2])], memory_slots=3)
    observed = observe_blocking(result, physical_neighbors={0: [1], 1: [0, 2], 2: [1]})
    assert observed["required_capacity_histogram"] == [{"capacity": 2, "attempts": 1},
                                                       {"capacity": 4, "attempts": 1}]
    assert observed["rejections_by_reason"] == {"neighbor_reservation": 1}
    pivot = next(row for row in observed["nodes"] if row["node"] == 1)
    assert pivot["local_full"] == 0


def test_capacity_histogram_uses_window_attempts_but_full_state_history():
    result = simulate([event(0, "generate", [0, 1]), event(1, "generate", [0, 1]),
                       event(2, "generate", [0, 1])], nodes=2)
    observed = observe_blocking(result, warmup=1, physical_neighbors={0: [1], 1: [0]})
    assert observed["required_capacity_histogram"] == [{"capacity": 2, "attempts": 1},
                                                       {"capacity": 3, "attempts": 1}]
    assert observed["offered"] == 2


@pytest.mark.parametrize("neighbors", [
    {0: [1], 1: [0, 2]},  # Missing node.
    {0: [1], 1: [2, 0], 2: [1]},  # Wrong reservation ordering.
    {0: [1], 1: [0, 2], 2: []},  # Not reciprocal.
    {0: [0, 1], 1: [0, 2], 2: [1]},  # Self edge.
    {0: [1, 1], 1: [0, 2], 2: [1]},  # Duplicate edge.
    {0: [1], 1: [0, 9], 2: [1]},  # Unknown node.
    {0: [1], 1: [0, 2], 2: [[]]},  # Unhashable invalid label.
    {0: [1], 1: [0], 2: []},  # Missing an observed physical edge.
])
def test_invalid_physical_adjacency_is_rejected(neighbors):
    result = simulate([event(1, "generate", [1, 2])])
    with pytest.raises(ValueError, match="physical_neighbors"):
        observe_blocking(result, physical_neighbors=neighbors)


def test_finite_reservations_validate_zero_arrival_physical_edges():
    result = simulate([event(1, "generate", [0, 1])], memory_slots=4)
    with pytest.raises(ValueError, match="recorded reservations"):
        observe_blocking(result, physical_neighbors={0: [1], 1: [0], 2: []})


def test_quota_capacity_predictor_rejects_tail_drop_policy():
    result = simulate([], admission_policy="tail_drop")
    with pytest.raises(ValueError, match="reserved admission"):
        observe_blocking(result, physical_neighbors={0: [1], 1: [0, 2], 2: [1]})

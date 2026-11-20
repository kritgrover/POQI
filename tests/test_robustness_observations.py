"""Disjoint observation windows preserve queue carry-over and boundary events."""

import copy

import networkx as nx
import pytest

from poqi.simulation import run_simulation
from scripts.robustness_observations import observe_robustness


def event(time, kind, endpoints=(0, 1), count=1):
    return {"time": time, "kind": kind, "endpoints": list(endpoints), "count": count}


def simulate(trace, *, chain=False, **kwargs):
    graph = nx.path_graph(3 if chain else 2)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return run_simulation(graph, {(0, 2) if chain else (0, 1): 1.0}, trace=trace,
                          ticks_per_time_unit=100, horizon=kwargs.pop("horizon", 8),
                          **kwargs).to_dict()


def test_disjoint_windows_integrate_old_queue_and_split_tick_events():
    data = simulate([event(0, "request", count=3), event(2, "generate"), event(3, "request"),
                     event(4, "generate"), event(4, "request"), event(6, "generate"), event(7, "request")])
    early, late = observe_robustness(data, warmup=1, split=4)["windows"]
    assert (early["window"], early["start"], early["end"]) == ("early", 1, 4)
    assert (late["window"], late["start"], late["end"]) == ("late", 4, 8)
    assert early["initial_backlog"] == early["final_backlog"] == 3
    assert late["initial_backlog"] == late["final_backlog"] == 3
    assert early["offered_requests"] == early["completed_requests"] == early["offered_generation"] == 1
    assert late["offered_requests"] == late["completed_requests"] == late["offered_generation"] == 2
    assert early["mean_backlog"] == pytest.approx(8 / 3)
    assert late["mean_backlog"] == pytest.approx(11 / 4)
    assert early["backlog_growth_rate"] == late["backlog_growth_rate"] == 0
    assert early["blocking_probability"] == late["blocking_probability"] == 0
    assert not early["single_partner_absorbing_stall"]


def test_warmup_and_split_zero_time_service_belongs_to_right_window():
    data = simulate([event(1, "generate"), event(1, "request"),
                     event(4, "generate"), event(4, "request")])
    early, late = observe_robustness(data, warmup=1, split=4)["windows"]
    for row in (early, late):
        assert row["initial_backlog"] == row["final_backlog"] == row["mean_backlog"] == 0
        assert row["offered_requests"] == row["completed_requests"] == row["offered_generation"] == 1
        assert not row["zero_service"]


def test_horizon_expiry_does_not_enter_either_window():
    data = simulate([event(1, "generate")], cutoff_time=7)
    assert any(e["kind"] == "expire" and e["tick"] == 800 for e in data["events"])
    early, late = observe_robustness(data, warmup=0, split=4)["windows"]
    assert early["offered_generation"] == 1 and late["offered_generation"] == 0
    assert early["blocking_probability"] == 0 and late["blocking_probability"] is None
    assert early["swaps_per_completion"] is late["swaps_per_completion"] is None
    assert early["zero_service"] and late["zero_service"]
    assert not early["zero_service_with_demand"] and not late["zero_service_with_demand"]


def test_queue_growth_counts_arrivals_without_completions():
    data = simulate([event(0, "request", count=2), event(2, "request"), event(5, "request", count=2)])
    early, late = observe_robustness(data, warmup=1, split=4)["windows"]
    assert (early["initial_backlog"], early["final_backlog"]) == (2, 3)
    assert (late["initial_backlog"], late["final_backlog"]) == (3, 5)
    assert early["backlog_growth_rate"] == pytest.approx(1 / 3)
    assert late["backlog_growth_rate"] == .5
    assert early["zero_service_with_demand"] and late["zero_service_with_demand"]


def test_carried_request_counts_as_demand_without_new_window_arrivals():
    data = simulate([event(0, "request")])
    early, late = observe_robustness(data, warmup=1, split=4)["windows"]
    for row in (early, late):
        assert row["offered_requests"] == row["completed_requests"] == 0
        assert row["initial_backlog"] == row["final_backlog"] == 1
        assert row["zero_service_with_demand"]


def pressure_trace():
    return simulate([event(0, "request", (0, 2)), event(1, "generate", (0, 1)),
                     event(2, "generate", (1, 2))], chain=True,
                    swap_policy="pressure_relaxed", memory_slots=2)


def test_relaxed_swap_and_completion_at_split_are_only_late():
    early, late = observe_robustness(pressure_trace(), warmup=0, split=2)["windows"]
    assert early["swaps"] == early["pressure_relaxed_swaps"] == early["completed_requests"] == 0
    assert early["final_backlog"] == late["initial_backlog"] == 1
    assert late["swaps"] == late["pressure_relaxed_swaps"] == late["completed_requests"] == 1
    assert late["swaps_per_completion"] == 1
    assert early["mean_backlog"] == 1 and late["mean_backlog"] == 0


def absorbing_trace(*, cutoff=None, request=True):
    trace = [event(1, "generate", (0, 1)), event(2, "generate", (1, 2)),
             event(3, "generate", (1, 2)), event(4, "generate", (0, 1))]
    if request:
        trace.append(event(5, "request", (0, 2)))
    trace.extend([event(6, "generate", (0, 1)), event(6, "generate", (1, 2))])
    return simulate(trace, chain=True, swap_policy="pressure_relaxed", memory_slots=2, cutoff_time=cutoff)


def test_absorbing_stall_is_state_at_end_not_a_zero_service_heuristic():
    data = absorbing_trace()
    early, late = observe_robustness(data, warmup=0, split=6)["windows"]
    assert early["single_partner_absorbing_stall"] and late["single_partner_absorbing_stall"]
    assert early["zero_service_with_demand"] and late["zero_service_with_demand"]
    assert early["swaps"] == early["pressure_relaxed_swaps"] == 2
    assert late["swaps"] == late["pressure_relaxed_swaps"] == 0
    assert late["rejected_generation"] == late["offered_generation"] == 2
    assert late["blocking_probability"] == 1


def test_stall_classifier_excludes_request_exactly_at_boundary():
    early, late = observe_robustness(absorbing_trace(), warmup=0, split=5)["windows"]
    assert not early["single_partner_absorbing_stall"]
    assert late["single_partner_absorbing_stall"]


@pytest.mark.parametrize("cutoff,with_request", [(10, True), (None, False)])
def test_single_partner_shape_is_not_classified_with_expiry_or_no_pending_demand(cutoff, with_request):
    rows = observe_robustness(absorbing_trace(cutoff=cutoff, request=with_request), warmup=0, split=6)["windows"]
    assert all(not r["single_partner_absorbing_stall"] for r in rows)


def test_expiry_at_split_allows_late_recovery_from_single_partner_shape():
    data = absorbing_trace(cutoff=5)
    early, late = observe_robustness(data, warmup=0, split=6)["windows"]
    assert any(e["kind"] == "expire" and e["tick"] == 600 for e in data["events"])
    assert early["completed_requests"] == 0
    assert early["final_backlog"] == late["initial_backlog"] == 1
    assert late["completed_requests"] == 1 and late["final_backlog"] == 0
    assert not early["single_partner_absorbing_stall"] and not late["single_partner_absorbing_stall"]


def test_other_structural_stall_is_not_claimed_by_single_partner_detector():
    data = simulate([event(0, "request", (0, 2)), event(1, "generate", (0, 1)),
                     event(2, "generate", (1, 2))], chain=True, memory_slots=2)
    rows = observe_robustness(data, warmup=0, split=4)["windows"]
    assert all(r["zero_service"] and not r["single_partner_absorbing_stall"] for r in rows)


def test_full_log_counter_corruption_is_still_rejected():
    data = pressure_trace()
    data["pressure_relaxed_swaps"] += 1
    with pytest.raises(ValueError, match="relaxed counter"):
        observe_robustness(data, warmup=0, split=2)


@pytest.mark.parametrize("warmup,split", [(-1, 4), (4, 4), (5, 4), (0, 8), (True, 4), (0, float("nan")), (0, .015)])
def test_invalid_or_non_tick_aligned_windows_fail(warmup, split):
    with pytest.raises(ValueError, match="windows"):
        observe_robustness(simulate([]), warmup=warmup, split=split)


def test_observation_does_not_mutate_saved_simulation():
    data = pressure_trace()
    original = copy.deepcopy(data)
    result = observe_robustness(data, warmup=0, split=2)
    assert data == original
    assert len(result["input_signature"]) == len(result["event_signature"]) == 64

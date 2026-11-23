"""Independent workload, time-window and physical-opportunity checks."""

from collections import deque
from copy import deepcopy
import math

import pytest

from scripts import qcast_pilot as pilot


def test_potential_outcomes_are_keyed_to_hardware_not_policy_actions():
    channels = pilot.specification("chain")[-1]
    u, order = pilot.opportunities("chain", 6271, 4, channels)
    assert u == pilot.opportunities("chain", 6271, 4, channels)[0]
    assert all(0 <= value < 1 for value in u)
    assert len(set(u)) == len(channels)
    assert sorted(order) == sorted(channels)
    # Choice changes realized successes but never potential outcomes.
    all_selected = [i for i in range(4) if u[i] < .5]
    subset = [i for i in [1, 3] if u[i] < .5]
    assert subset == [i for i in all_selected if i in {1, 3}]
    assert all(value < 1 for value in u)
    assert not any(value < 0 for value in u)


def test_shared_workload_preserves_pair_counts_and_true_arrival_times():
    requests = pilot.workload("diamond", 6271, 100)
    assert requests == pilot.workload("diamond", 6271, 100)
    assert [r["id"] for r in requests] == list(range(len(requests)))
    assert [r["arrival"] for r in requests] == sorted(r["arrival"] for r in requests)
    assert all(0 < r["arrival"] < 100 for r in requests)
    assert {tuple(r["pair"]) for r in requests} == {(0, 3), (0, 1), (1, 2)}


def test_fifo_does_not_spend_a_later_pairs_ebit_on_wrong_request():
    pending = deque([{"id": 0, "pair": [0, 2]}, {"id": 1, "pair": [0, 1]}])
    completions, counts = [], {(0, 1): 2}
    assert pilot.serve_fifo(pending, counts, 3, completions) == []
    assert counts[(0, 1)] == 2
    counts[(0, 2)] = 1
    assert pilot.serve_fifo(pending, counts, 4, completions) == [0, 1]
    assert counts == {(0, 1): 1, (0, 2): 0}


@pytest.mark.parametrize("arm", pilot.ARMS[1:])
@pytest.mark.parametrize("p", [0.5, 1.0])
def test_opportunity_arms_match_physical_ledger_and_waiting_identity(arm, p):
    result = pilot.run_trajectory("chain", 3, p, 6201, arm, 12, None)
    observed = pilot.observe(result, 3)
    assert pilot.audit_trajectory(result)
    finished = {row["id"]: row["time"] for row in result["completions"]}
    # Independent event sweep of true backlog, including invisible requests.
    events = [(r["arrival"], 1) for r in result["requests"]]
    events += [(row["time"], -1) for row in result["completions"]]
    events.sort()
    backlog = 0
    previous = area = 0
    for tick, delta in events + [(12, 0)]:
        area += backlog * max(0, min(tick, 12)-max(previous, 3))
        backlog += delta
        previous = tick
    assert backlog == observed["final_backlog"]
    assert area/9 == pytest.approx(observed["mean_backlog"])
    assert observed["completed"] == sum(3 < tick <= 12 for tick in finished.values())
    assert observed["final_backlog"] == len(result["requests"])-len(finished)
    assert observed["allocated_qubits_mean"] <= 3*3


def test_no_service_is_retained_with_undefined_operation_ratios():
    result = pilot.run_trajectory("chain", 2, 1, 6201, "POQI-Slot-balancing", 12, None)
    row = pilot.observe(result, 3)
    assert row["zero_service"]
    assert row["completed"] == row["throughput"] == 0
    assert row["attempts_per_completion"] is None
    assert row["swaps_per_completion"] is None
    assert row["unfinished_mean_age"] > 0
    assert row["final_backlog"] == len(result["requests"])


def test_last_slot_arrivals_remain_in_pending_backlog(monkeypatch):
    fixed = [{"id": 0, "pair": [0, 3], "arrival": .25},
             {"id": 1, "pair": [0, 3], "arrival": 11.25}]
    monkeypatch.setattr(pilot, "workload", lambda *args: deepcopy(fixed))
    result = pilot.run_trajectory("diamond", 4, 1, 6201, "POQI-Slot-pressure_relaxed", 12, None)
    late = {r["id"] for r in result["requests"] if r["arrival"] > 11}
    assert late
    assert late <= set(result["pending"])
    assert not late.intersection(r["id"] for r in result["completions"])


def test_service_at_measurement_start_excluded_and_final_end_included(monkeypatch):
    # A synthetic observer fixture, with the physical audit replaced only for
    # this independent boundary arithmetic test.
    monkeypatch.setattr(pilot, "audit_trajectory", lambda data: True)
    requests = [{"id": 0, "pair": [0, 2], "arrival": .25},
                {"id": 1, "pair": [0, 2], "arrival": 1.25},
                {"id": 2, "pair": [0, 2], "arrival": 2.75}]
    slot = {"selected": [], "successful": [], "swaps": 0, "qubit_time": 0,
            "storage_qubit_time": 0, "expired_pairs": 0, "discarded_pairs": 0}
    data = {"horizon": 3, "requests": requests,
            "completions": [{"id": 0, "time": 1}, {"id": 1, "time": 3}],
            "slots": [slot.copy() for _ in range(3)], "topology": "chain", "memory": 2,
            "p": 1, "arm": pilot.ARMS[0], "seed": 1, "channels": [0, 1, 2, 3],
            "workload_sha256": "x", "potential_sha256": "y"}
    observed = pilot.observe(data, 1)
    assert observed["completed"] == 1
    assert observed["completed_mean_latency"] == 1.75
    assert observed["initial_backlog"] == 0
    assert observed["final_backlog"] == 1
    assert observed["mean_backlog"] == 1  # 1.75 + .25, over two time units
    assert observed["restricted_mean_wait_full_horizon"] == pytest.approx((.75+1.75+.25)/3)


@pytest.mark.parametrize("corruption", ["attempt", "outcome", "memory", "cost", "fifo", "pending", "stock"])
def test_corrupt_physical_or_workload_records_are_rejected(corruption):
    data = pilot.run_trajectory("chain", 4, 1, 6201, "POQI-Slot-balancing", 12, None)
    row = data["slots"][0]
    if corruption == "attempt":
        row["selected"].append(row["selected"][0])
    elif corruption == "outcome":
        row["successful"].pop()
    elif corruption == "memory":
        row["reserved_occupancy"][0] = 5
    elif corruption == "cost":
        row["qubit_time"] = 0
    elif corruption == "fifo":
        data["completions"][0]["id"] += 1
    elif corruption == "pending":
        data["pending"].append(999)
    elif corruption == "stock":
        row["discarded_pairs"] += 1
    with pytest.raises(ValueError):
        pilot.audit_trajectory(data)


def test_intervals_report_undefined_ratios_without_dropping_zero_runs():
    assert pilot.interval([None, None]) == {"mean": None, "low": None, "high": None, "n": 0, "undefined": 2}
    summary = pilot.interval([0, 0, 0])
    assert summary["n"] == 3 and summary["mean"] == 0
    partial = pilot.interval([None, 1, 3])
    assert partial["undefined"] == 1 and partial["mean"] == 2


@pytest.mark.parametrize("horizon,warmup,seeds", [(0, 0, [1]), (3, 3, [1]), (2001, 0, [1]),
                                                (3, 0, []), (3, 0, [1, 1])])
def test_invalid_run_design_is_rejected_before_creation(tmp_path, horizon, warmup, seeds):
    with pytest.raises(ValueError):
        pilot.run_suite(tmp_path / "invalid", horizon, warmup, seeds)
    assert not (tmp_path / "invalid").exists()

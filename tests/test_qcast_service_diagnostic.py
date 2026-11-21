"""Service-mechanism controls, censoring arithmetic and native replay checks."""

from collections import deque
from copy import deepcopy
import os
from pathlib import Path

import pytest

from scripts import qcast_pilot as pilot
from scripts import qcast_service_diagnostic as diagnostic


def request(identifier, pair, arrival=0):
    return {"id": identifier, "pair": list(pair), "arrival": arrival}


def test_concurrent_service_bypasses_unavailable_global_head_but_keeps_pair_order():
    pending = deque([request(0, (0, 3)), request(1, (0, 1)), request(2, (0, 1)),
                     request(3, (1, 2)), request(4, (0, 1))])
    fifo = deepcopy(pending)
    counts = {(0, 3): 0, (0, 1): 2, (1, 2): 1}
    assert pilot.serve_fifo(fifo, counts.copy(), 1, []) == []
    completions = []
    assert diagnostic.consume_concurrent(pending, counts, 1, completions) == [1, 2, 3]
    assert [r["id"] for r in pending] == [0, 4]
    assert completions == [{"id": i, "time": 1} for i in [1, 2, 3]]
    assert counts == {(0, 3): 0, (0, 1): 0, (1, 2): 0}
    assert diagnostic.consume_concurrent(pending, counts, 2, completions) == []


@pytest.mark.parametrize("invalid", [-1, 0.5, True])
def test_service_rejects_invalid_physical_counts(invalid):
    with pytest.raises(ValueError, match="physical ebit"):
        diagnostic.consume_concurrent(deque(), {(0, 1): invalid}, 0, [])


def simple_record():
    slots = [{"selected": [0, 1], "successful": [0], "swaps": 0,
              "qubit_time": 4, "discarded_pairs": 1,
              "native": {"author_accounting_discrepancy": False}} for _ in range(4)]
    return {"seed": 1, "topology": "diamond", "horizon": 4,
            "requests": [request(0, (0, 3), .2), request(1, (0, 1), .5),
                         request(2, (0, 3), 1.5), request(3, (1, 2), 3.5)],
            "completions": [{"id": 0, "time": 2}, {"id": 1, "time": 4}],
            "slots": slots, "workload_sha256": "requests", "potential_sha256": "potential"}


def test_observer_integrates_queue_and_retains_censored_waits():
    observed = diagnostic.measure(simple_record(), "concurrent_per_pair", 1)
    assert observed["completed"] == 2
    assert observed["throughput"] == pytest.approx(2/3)
    assert observed["completed_mean_latency"] == pytest.approx(2.65)
    assert observed["mean_backlog"] == pytest.approx(7/3)
    assert observed["initial_backlog"] == observed["final_backlog"] == 2
    assert observed["backlog_growth"] == 0
    assert observed["unfinished_mean_age"] == pytest.approx(1.5)
    assert observed["restricted_mean_wait_full_horizon"] == pytest.approx(2.075)
    assert observed["attempts"] == 6
    assert observed["attempts_per_completion"] == 3
    assert observed["allocated_qubits_mean"] == 4
    assert {tuple(r["pair"]): (r["completed"], r["pending"]) for r in observed["per_pair"]} == {
        (0, 3): (1, 1), (0, 1): (1, 0), (1, 2): (0, 1)}


def test_zero_service_is_retained_with_undefined_completion_ratios():
    data = simple_record()
    data["completions"] = []
    observed = diagnostic.measure(data, "fifo", 1)
    assert observed["zero_service"] is True
    assert observed["completed_mean_latency"] is None
    assert observed["attempts_per_completion"] is None
    assert observed["swaps_per_completion"] is None
    assert observed["final_backlog"] == 4


def test_paired_summary_preserves_undefined_latency_contrast():
    concurrent = diagnostic.measure(simple_record(), "concurrent_per_pair", 1)
    data = simple_record()
    data["completions"] = []
    fifo = diagnostic.measure(data, "fifo", 1)
    report = diagnostic.summarize([concurrent, fifo])
    assert report["paired_concurrent_minus_fifo"]["throughput"]["mean"] == pytest.approx(2/3)
    latency = report["paired_concurrent_minus_fifo"]["completed_mean_latency"]
    assert latency["mean"] is None and latency["n"] == 0 and latency["undefined"] == 1
    assert report["summaries"][0]["zero_service_runs"] == 1


@pytest.mark.parametrize("corruption", ["duplicate", "seed", "workload", "potential"])
def test_pairing_rejects_invalid_observation_sets(corruption):
    rows = [diagnostic.measure(simple_record(), mode, 1) for mode in diagnostic.MODES]
    if corruption == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif corruption == "seed":
        rows[1]["seed"] = 2
    else:
        rows[1][f"{corruption}_sha256"] = "corrupted"
    with pytest.raises(ValueError):
        diagnostic.summarize(rows)


@pytest.fixture(scope="module")
def native_records(tmp_path_factory):
    build = os.environ.get("QCAST_PILOT_BUILD")
    if not build:
        pytest.skip("QCAST_PILOT_BUILD not set: service diagnostic native check unavailable")
    directory = tmp_path_factory.mktemp("service-native")
    with pilot.NativeBridge(Path(build), directory / "stderr.log") as bridge:
        fifo = pilot.run_trajectory("diamond", 4, .5, 6271, pilot.ARMS[0], 20, bridge)
        concurrent = diagnostic.run_concurrent(6271, 20, bridge)
    return fifo, concurrent


def test_native_service_modes_pass_independent_replay(native_records):
    for mode, record in zip(diagnostic.MODES, native_records):
        assert diagnostic.audit(record, mode)
    fifo = native_records[0]
    independent = diagnostic.measure(fifo, "fifo", 5)
    original = pilot.observe(fifo, 5)
    assert all(independent[key] == original[key] for key in diagnostic.METRICS)
    assert native_records[0]["workload_sha256"] == native_records[1]["workload_sha256"]
    assert native_records[0]["potential_sha256"] == native_records[1]["potential_sha256"]


@pytest.mark.parametrize("corruption", ["completion", "pending", "request", "opportunity", "reset_loss", "physical_count"])
def test_native_replay_rejects_corrupt_records(native_records, corruption):
    record = deepcopy(native_records[1])
    nonempty = next(row for row in record["slots"] if row["selected"])
    if corruption == "completion":
        record["completions"].append({"id": 0, "time": 20})
    elif corruption == "pending":
        record["pending"].append(999)
    elif corruption == "request":
        record["requests"][0]["arrival"] += .1
    elif corruption == "opportunity":
        nonempty["selected"].append(nonempty["selected"][0])
    elif corruption == "reset_loss":
        nonempty["discarded_pairs"] += 1
    else:
        delivery = next(row["native"]["delivered"][0] for row in record["slots"] if row["native"]["delivered"])
        delivery["count"] += 1
    with pytest.raises(ValueError):
        diagnostic.audit(record, "concurrent_per_pair")

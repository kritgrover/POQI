"""Matched-service semantics, prior replay, censoring and provenance guards."""

from collections import deque
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path

import pytest

from scripts import qcast_concurrent as concurrent
from scripts import qcast_pilot as pilot


def request(identifier, pair):
    return {"id": identifier, "pair": list(pair), "arrival": .25}


def test_concurrent_serves_oldest_per_pair_preserves_retained_order_across_phases():
    queue = deque([request(0, (0, 3)), request(1, (0, 1)), request(2, (0, 1)),
                   request(3, (1, 2)), request(4, (0, 1)), request(5, (0, 3))])
    completed, calls = [], []
    def consume(pair, tick):
        calls.append((pair, tick))
        return {"physical_id": len(calls)}
    counts = {(0, 1): 2, (1, 2): 1}
    assert concurrent.serve_requests(queue, counts, 5, completed, "concurrent_per_pair", consume) == [1, 2, 3]
    assert [r["id"] for r in queue] == [0, 4, 5]
    assert counts == {(0, 1): 0, (1, 2): 0}
    assert concurrent.serve_requests(queue, {(0, 3): 1}, 6, completed, "concurrent_per_pair", consume) == [0]
    assert [r["id"] for r in queue] == [4, 5]
    assert calls == [((0, 1), 5), ((0, 1), 5), ((1, 2), 5), ((0, 3), 6)]
    assert [r["id"] for r in completed] == [1, 2, 3, 0]
    assert len({r["id"] for r in completed}) == len(completed)


@pytest.mark.parametrize("mode", concurrent.SERVICE_MODES)
def test_physical_callback_cannot_manufacture_missing_pair(mode):
    queue = deque([request(0, (0, 1))])
    completed = []
    with pytest.raises(AssertionError):
        concurrent.serve_requests(queue, {(0, 1): 1}, 1, completed, mode, lambda *_: None)
    assert completed == []


@pytest.mark.parametrize("mode", concurrent.SERVICE_MODES)
def test_unavailable_pair_does_not_invoke_physical_callback(mode):
    queue = deque([request(0, (0, 1))])
    def forbidden(*_):
        pytest.fail("a nonexistent physical resource was consumed")
    assert concurrent.serve_requests(queue, {}, 1, [], mode, forbidden) == []
    assert len(queue) == 1


@pytest.mark.parametrize("counts", [{(0, 1): -1}, {(0, 1): .5}, {(0, 1): True}])
def test_service_rejects_nonphysical_counts(counts):
    with pytest.raises(ValueError, match="counts"):
        concurrent.serve_requests(deque(), counts, 1, [], "concurrent_per_pair")


def test_fifo_remains_blocked_by_oldest_unavailable_pair():
    queue = deque([request(0, (0, 3)), request(1, (0, 1))])
    counts = {(0, 1): 1}
    assert concurrent.serve_requests(queue, counts, 1, [], "fifo") == []
    assert counts[(0, 1)] == 1
    with pytest.raises(ValueError, match="service_mode"):
        concurrent.serve_requests(queue, counts, 1, [], "shortest_path")


@pytest.mark.parametrize("arm", pilot.ARMS[1:])
@pytest.mark.parametrize("p", [.5, 1.0])
def test_single_pair_service_modes_and_previous_pilot_are_exactly_equivalent(arm, p):
    fifo = concurrent.run_trajectory("chain", 3, p, 7271, arm, 25, None, "fifo")
    parallel = concurrent.run_trajectory("chain", 3, p, 7271, arm, 25, None, "concurrent_per_pair")
    old = pilot.run_trajectory("chain", 3, p, 7271, arm, 25, None)
    assert fifo.pop("service_mode") == "fifo"
    assert parallel.pop("service_mode") == "concurrent_per_pair"
    assert fifo == parallel == old


@pytest.mark.parametrize("arm", pilot.ARMS[1:])
def test_diamond_fifo_exactly_replays_previous_pilot(arm):
    new = concurrent.run_trajectory("diamond", 4, .5, 7271, arm, 25, None, "fifo")
    new.pop("service_mode")
    assert new == pilot.run_trajectory("diamond", 4, .5, 7271, arm, 25, None)


@pytest.mark.parametrize("arm", concurrent.ARMS[3:])
def test_persistent_start_and_end_service_spend_each_physical_pair_once(monkeypatch, arm):
    calls = []
    original = pilot.PoqiOpportunityArm.consume
    def measured_consume(self, pair, tick):
        result = original(self, pair, tick)
        calls.append((pair, tick, result))
        return result
    monkeypatch.setattr(pilot.PoqiOpportunityArm, "consume", measured_consume)
    raw = concurrent.run_trajectory("diamond", 4, .5, 7271, arm, 40, None)
    assert any(row["start_completed"] for row in raw["slots"])
    assert any(row["end_completed"] for row in raw["slots"])
    assert len(calls) == len(raw["completions"])
    assert len({pair["id"] for _, _, pair in calls}) == len(calls)
    for (endpoints, tick, physical), event in zip(calls, raw["completions"]):
        assert list(endpoints) == raw["requests"][event["id"]]["pair"] == physical["endpoints"]
        assert tick == event["time"]
    # Every reserved attempt still costs two qubit-slots after cache service
    # frees occupied memory; service itself never increments attempt/swap cost.
    for row in raw["slots"]:
        assert row["qubit_time"] == row["storage_qubit_time"] + 2*len(row["selected"])
        assert row["swaps"] == len(row["settled"]["swap_log"])


def test_concurrent_zero_service_retains_all_requests_and_undefined_costs():
    raw = concurrent.run_trajectory("chain", 2, 1, 7271, "POQI-Slot-balancing", 25, None)
    row = concurrent.observe(raw, 5)
    assert row["zero_service"] and row["per_pair"][0]["zero_service"]
    assert row["completed"] == 0 and row["final_backlog"] == len(raw["requests"])
    assert row["attempts_per_completion"] is None and row["swaps_per_completion"] is None
    assert row["unfinished_mean_age"] > 0


def test_per_pair_censoring_measurement_boundaries_and_invisible_final_arrivals(monkeypatch):
    monkeypatch.setattr(concurrent, "audit_trajectory", lambda _: True)
    requests = [{"id": 0, "pair": [0, 3], "arrival": .25},
                {"id": 1, "pair": [0, 1], "arrival": 1.25},
                {"id": 2, "pair": [1, 2], "arrival": 2.75}]
    slot = {"selected": [], "successful": [], "swaps": 0, "qubit_time": 0,
            "storage_qubit_time": 0, "expired_pairs": 0, "discarded_pairs": 0}
    data = {"horizon": 3, "requests": requests,
            "completions": [{"id": 0, "time": 1}, {"id": 1, "time": 3}],
            "slots": [slot.copy() for _ in range(3)], "topology": "diamond", "memory": 2,
            "p": 1, "arm": pilot.ARMS[0], "service_mode": "concurrent_per_pair", "seed": 1,
            "channels": [], "workload_sha256": "x", "potential_sha256": "y"}
    row = concurrent.observe(data, 1)
    assert row["completed"] == 1 and row["throughput"] == .5
    assert row["mean_backlog"] == 1 and row["unfinished_mean_age"] == .25
    pairs = {tuple(r["pair"]): r for r in row["per_pair"]}
    assert pairs[0, 3]["completed"] == 0 and pairs[0, 3]["completed_mean_latency"] is None
    assert pairs[0, 1]["completed"] == 1 and pairs[0, 1]["completed_mean_latency"] == 1.75
    assert pairs[1, 2]["pending"] == 1 and pairs[1, 2]["unfinished_mean_age"] == .25
    assert sum(r["mean_backlog"] for r in pairs.values()) == row["mean_backlog"]
    assert sum(r["throughput"] for r in pairs.values()) == row["throughput"]


def observations_for_summary():
    raw = concurrent.run_trajectory("chain", 2, 1, 7271, "POQI-Slot-balancing", 12, None)
    base = concurrent.observe(raw, 3)
    return [{**deepcopy(base), "arm": arm, "service_mode": mode, "seed": seed}
            for arm in concurrent.ARMS for mode in concurrent.SERVICE_MODES for seed in (7271, 7272)]


def test_summary_pairs_every_mode_and_arm_and_retains_undefined_ratios():
    rows = observations_for_summary()
    report = concurrent.summarize(rows)
    assert len(report["summaries"]) == 14 and len(report["paired_contrasts"]) == 19
    assert {r["kind"] for r in report["paired_contrasts"]} == {"qcast_vs_poqi", "service_mode", "pressure_vs_balancing"}
    assert all(row["attempts_per_completion"]["n"] == 0 for row in report["summaries"])
    assert all(row["attempts_per_completion"]["undefined"] == 2 for row in report["paired_contrasts"])
    assert all(row["per_pair"][0]["zero_service_runs"] == 2 for row in report["summaries"])
    assert all(row["throughput"]["n"] == 2 for row in report["paired_contrasts"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "workload", "potential"])
def test_summary_rejects_invalid_pairing(mutation):
    rows = observations_for_summary()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[-1])
    else:
        rows[-1][mutation + "_sha256"] = "changed"
    with pytest.raises(ValueError):
        concurrent.summarize(rows)


@pytest.mark.parametrize("mutation", ["completion", "pending", "outcomes", "memory", "digest"])
def test_accounting_replay_rejects_mutated_trajectory(mutation):
    raw = concurrent.run_trajectory("diamond", 4, .5, 7271, "POQI-Slot-pressure_relaxed", 15, None)
    if mutation == "completion":
        raw["completions"].append({"id": 0, "time": 15})
    elif mutation == "pending":
        raw["pending"].append(0)
    elif mutation == "outcomes":
        raw["slots"][0]["successful"] = [999]
    elif mutation == "memory":
        raw["slots"][0]["reserved_occupancy"][0] = 5
    else:
        raw["potential_sha256"] = "changed"
    with pytest.raises(ValueError):
        concurrent.audit_trajectory(raw)


@pytest.mark.parametrize("kwargs", [{"horizon": 2001}, {"horizon": 10, "warmup": 10},
                                    {"seeds": [1, 1]}, {"seeds": [-1]}, {"seeds": []}])
def test_runner_rejects_unbounded_or_unpaired_design_before_creating_output(tmp_path, kwargs):
    destination = tmp_path / "never-created"
    with pytest.raises(ValueError):
        concurrent.run_suite(destination, **kwargs)
    assert not destination.exists()


@pytest.fixture
def fake_build(tmp_path):
    build = tmp_path / "build"
    bridge = build / "src/main/kotlin/poqi/qcast/SlotBridge.kt"
    bridge.parent.mkdir(parents=True)
    bridge.write_bytes(pilot.BRIDGE.read_bytes())
    source = build / "pom.xml"
    source.write_text("pinned fixture", encoding="utf-8")
    dependency = tmp_path / "dependency.jar"
    dependency.write_bytes(b"dependency fixture")
    (build / "classpath.txt").write_text(str(dependency), encoding="utf-8")
    classes = build / "target/classes"
    classes.mkdir(parents=True)
    (classes / "SlotBridge.class").write_bytes(b"compiled fixture")
    pilot.write_json(tmp_path / "build-manifest.json", {
        "revision": pilot.REVISION, "bridge_sha256": pilot.sha256(bridge),
        "source_hashes": {"pom.xml": pilot.sha256(source)},
        "dependency_hashes": {str(dependency): pilot.sha256(dependency)}})
    return build


@pytest.mark.parametrize("target", ["pom.xml", "src/main/kotlin/poqi/qcast/SlotBridge.kt", "classpath.txt", "dependency"])
def test_native_provenance_rejects_changed_build_inputs(fake_build, target):
    before = concurrent.verify_build(fake_build)
    assert before["runtime_hashes"] and before["dependency_hashes"]
    destination = fake_build.parent / "dependency.jar" if target == "dependency" else fake_build / target
    destination.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError):
        concurrent.verify_build(fake_build)


def test_native_runtime_fingerprint_detects_changed_class(fake_build):
    before = concurrent.verify_build(fake_build)
    (fake_build / "target/classes/SlotBridge.class").write_bytes(b"changed")
    after = concurrent.verify_build(fake_build)
    assert before["runtime_hashes"] != after["runtime_hashes"]


@pytest.fixture(scope="module")
def native_bridge(tmp_path_factory):
    build = os.environ.get("QCAST_PILOT_BUILD")
    if not build:
        pytest.skip("set QCAST_PILOT_BUILD to the validated native bridge build")
    concurrent.verify_build(build)
    with pilot.NativeBridge(build, tmp_path_factory.mktemp("qcast-concurrent") / "bridge.log") as bridge:
        yield bridge


@pytest.mark.parametrize("arm", concurrent.ARMS)
def test_saved_primary_fifo_trajectory_exact_replay(native_bridge, arm):
    directory = Path(os.environ.get("QCAST_PILOT_MAIN_DIR", pilot.ROOT / "results/qcast/pilot-main-01"))
    old_arm = pilot.ARMS[0] if arm == concurrent.ARMS[0] else arm
    path = directory / f"runs/diamond-m4-p0.5-6271-{old_arm}.json.gz"
    if not path.is_file():
        pytest.skip("saved previous primary trajectory unavailable")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        previous = json.load(stream)
    current = concurrent.run_trajectory("diamond", 4, .5, 6271, arm, previous["horizon"], native_bridge, "fifo")
    current.pop("service_mode")
    current["arm"] = old_arm
    assert current == previous


def test_saved_native_concurrent_diagnostic_exact_replay(native_bridge):
    path = pilot.ROOT / "results/qcast/pilot-service-diagnostic/runs/concurrent_per_pair-6271.json.gz"
    if not path.is_file():
        pytest.skip("saved previous concurrent diagnostic unavailable")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        previous = json.load(stream)
    current = concurrent.run_trajectory("diamond", 4, .5, 6271, concurrent.ARMS[0], previous["horizon"], native_bridge)
    previous["arm"] = concurrent.ARMS[0]
    previous.setdefault("service_mode", "concurrent_per_pair")
    assert current == previous

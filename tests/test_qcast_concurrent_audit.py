"""Independent service, physical, censoring, reporting and provenance checks."""

from collections import Counter, deque
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path

import pytest

from scripts import qcast_concurrent as producer
from scripts import qcast_concurrent_audit as audit
from scripts import qcast_pilot as pilot
from scripts import qcast_pilot_audit as old_audit


@pytest.fixture(scope="module")
def records():
    return {(arm, mode): producer.run_trajectory("diamond", 4, .5, 7271, arm, 40, None, mode)
            for arm in audit.ARMS[1:] for mode in audit.MODES}


@pytest.mark.parametrize("mode", audit.MODES)
@pytest.mark.parametrize("arm", audit.ARMS[1:])
def test_independent_physical_replay_and_every_observation(records, arm, mode):
    data = records[arm, mode]
    assert audit.replay(data) == len(data["completions"])
    audit.close(audit.observation(data, 10), producer.observe(data, 10))


def call_service(mode, pending, counts, expected, requests, completions=None, live=None):
    completed = [] if completions is None else completions
    token = audit._mode.set(mode)
    try:
        audit.serve(pending, counts, expected, 5, requests, completed, live)
    finally:
        audit._mode.reset(token)
    return completed


@pytest.fixture
def mixed_requests():
    return [{"id": index, "pair": list(pair), "arrival": .25+index/10}
            for index, pair in enumerate([(0, 3), (0, 1), (0, 1), (1, 2), (0, 3), (0, 1)])]


def test_old_auditor_is_not_modified_and_context_resets(records, mixed_requests):
    assert old_audit.serve is not audit.serve
    assert old_audit.replay.__globals__["serve"] is old_audit.serve
    assert audit._physical.replay.__globals__["serve"] is audit.serve
    assert audit._mode.get() is None
    audit.replay(records[audit.ARMS[1], "fifo"])
    assert audit._mode.get() is None
    pending = deque(range(len(mixed_requests)))
    old_audit.serve(pending, Counter({(0, 1): 1}), [], 5, mixed_requests, [])
    assert list(pending) == list(range(len(mixed_requests)))
    bad = deepcopy(records[audit.ARMS[1], "concurrent_per_pair"])
    bad["potential_sha256"] = "wrong"
    with pytest.raises(ValueError):
        audit.replay(bad)
    assert audit._mode.get() is None


@pytest.mark.parametrize("mode,expected,retained", [
    ("fifo", [], [0, 1, 2, 3, 4, 5]),
    ("concurrent_per_pair", [1, 2, 3], [0, 4, 5]),
])
def test_service_scans_actual_counts_and_keeps_oldest_within_pair(mixed_requests, mode, expected, retained):
    pending, counts = deque(range(6)), Counter({(0, 1): 2, (1, 2): 1})
    completed = call_service(mode, pending, counts, expected, mixed_requests)
    assert list(pending) == retained
    assert [item["id"] for item in completed] == expected
    assert sum(counts.values()) == 3-len(expected)


@pytest.mark.parametrize("claimed", [[0], [2, 1, 3], [1, 1, 3], [1, 3], [1, 2, 3, 5]])
def test_rejects_wrong_pair_later_before_earlier_duplicated_or_omitted_service(mixed_requests, claimed):
    with pytest.raises(ValueError, match="service order/resource"):
        call_service("concurrent_per_pair", deque(range(6)), Counter({(0, 1): 2, (1, 2): 1}), claimed, mixed_requests)


def test_each_physical_pair_is_spent_once_across_start_and_end(mixed_requests):
    live = {17: {"id": 17, "endpoints": [0, 1], "deadline_tick": None, "admitted_tick": 0},
            18: {"id": 18, "endpoints": [0, 1], "deadline_tick": 10, "admitted_tick": 1}}
    queue, completed = deque(range(6)), []
    call_service("concurrent_per_pair", queue, Counter({(0, 1): 1}), [1], mixed_requests, completed, live)
    assert set(live) == {17}  # earliest expiry is the actual consumed physical input
    call_service("concurrent_per_pair", queue, Counter({(0, 1): 1}), [2], mixed_requests, completed, live)
    assert live == {}
    assert list(queue) == [0, 3, 4, 5]
    with pytest.raises(ValueError, match="without a physical pair"):
        call_service("concurrent_per_pair", queue, Counter({(0, 1): 1}), [5], mixed_requests, completed, live)


@pytest.mark.parametrize("corruption", [
    "unserved_omitted", "wrong_pair_completion", "duplicate_completion", "start_phase",
    "end_phase", "slot_boundary", "trial_cost", "storage_cost", "capacity",
    "selected_reuse", "false_success", "origin", "expiry", "swap_input", "cold_start",
    "reset", "mode", "schema", "pending_reuse",
])
def test_independent_replay_rejects_corrupted_physics_and_service(records, corruption):
    data = deepcopy(records["POQI-Cutoff10-pressure_relaxed", "concurrent_per_pair"])
    slots = data["slots"]
    generated = next(row for row in slots if row["settled"]["generated"])
    swapped = next(row for row in slots if row["settled"]["swap_log"])
    ended = next(row for row in slots if row["end_completed"])
    if corruption == "unserved_omitted":
        data["pending"].pop()
    elif corruption == "wrong_pair_completion":
        source = ended["end_completed"][0]
        ended["end_completed"][0] = next(row["id"] for row in data["requests"] if row["pair"] != data["requests"][source]["pair"])
    elif corruption == "duplicate_completion":
        data["completions"].append(data["completions"][0])
    elif corruption == "start_phase":
        next(row for row in slots if row["start_completed"])["start_completed"] = []
    elif corruption == "end_phase":
        ended["end_completed"] = []
    elif corruption == "slot_boundary":
        slots[1]["start"] = 2
    elif corruption == "trial_cost":
        generated["qubit_time"] += 2
    elif corruption == "storage_cost":
        generated["storage_qubit_time"] += 2
    elif corruption == "capacity":
        generated["reserved_occupancy"][0] = data["memory"]+1
    elif corruption == "selected_reuse":
        generated["selected"].append(generated["selected"][0])
    elif corruption == "false_success":
        generated["successful"] = []
    elif corruption == "origin":
        generated["settled"]["generated"][0]["pair"]["origins"][0]["neighbor"] = 99
    elif corruption == "expiry":
        swapped["settled"]["swap_log"][0]["created"][0]["deadline_tick"] += 1
    elif corruption == "swap_input":
        swapped["settled"]["swap_log"][0]["removed"].reverse()
    elif corruption == "cold_start":
        slots[0]["allocation"]["pre_live_pairs"] = 1
    elif corruption == "reset":
        generated["discarded_pairs"] += 1
    elif corruption == "mode":
        data["service_mode"] = "shortest_path"
    elif corruption == "schema":
        data["schema_version"] = 2
    else:
        data["pending"].append(data["pending"][0])
    with pytest.raises(ValueError):
        audit.replay(data)


def test_waiting_integrates_hidden_and_unserved_arrivals_and_excludes_warmup_boundary_service():
    offered = [{"id": 0, "arrival": .25}, {"id": 1, "arrival": .5},
               {"id": 2, "arrival": 2.75}, {"id": 3, "arrival": 3.75}]
    observed = audit.pair_observation(offered, [{"id": 0, "time": 1}, {"id": 1, "time": 4}], 4, 1)
    assert observed["completed"] == 1  # service at warmup 1 excluded, horizon 4 included
    assert observed["initial_backlog"] == 1
    assert observed["pending"] == observed["final_backlog"] == 2
    assert observed["mean_backlog"] == pytest.approx((3+1.25+.25)/3)
    assert observed["restricted_mean_wait_full_horizon"] == pytest.approx((.75+3.5+1.25+.25)/4)
    assert observed["unfinished_mean_age"] == .75
    assert observed["completed_mean_latency"] == 3.5


def test_zero_service_and_absorbing_control_remain_observed():
    raw = producer.run_trajectory("chain", 2, .5, 7273, "POQI-Persistent-pressure_relaxed", 60, None)
    audit.replay(raw)
    observed = audit.observation(raw, 20)
    audit.close(observed, producer.observe(raw, 20))
    assert observed["zero_service"] and observed["absorbing_stall"]
    assert observed["per_pair"][0]["pending"] > 0
    assert observed["per_pair"][0]["completed_mean_latency"] is None
    assert observed["attempts_per_completion"] is None
    assert observed["restricted_mean_wait_full_horizon"] > 0


@pytest.fixture(scope="module")
def observations(records):
    # Abstract observations are sufficient to validate the statistics; native
    # physical correctness is checked separately, never claimed by these rows.
    rows = []
    for seed in (7271, 7272, 7273):
        for arm in audit.ARMS:
            for mode in audit.MODES:
                row = audit.observation(records[arm if arm != audit.ARMS[0] else audit.ARMS[1], mode], 10)
                row.update(seed=seed, arm=arm)
                row["throughput"] += (seed-7271)/100
                rows.append(row)
    return rows


def test_every_group_contrast_and_pair_interval_reconstructs_independently(observations):
    expected = producer.summarize(observations)
    actual = audit.reconstruct_report(observations)
    audit.close(actual, expected)
    assert len(actual["summaries"]) == 14
    assert len(actual["paired_contrasts"]) == 19
    assert len(actual["summaries"][0]["per_pair"]) == 3
    assert all(row["throughput"]["n"] == 3 for row in actual["paired_contrasts"])


@pytest.mark.parametrize("corruption", ["omitted_seed", "duplicate_seed", "input_pairing", "pair_class", "mode"])
def test_report_reconstruction_rejects_missing_or_unpaired_inputs(observations, corruption):
    rows = deepcopy(observations)
    if corruption == "omitted_seed":
        rows.pop()
    elif corruption == "duplicate_seed":
        rows.append(rows[0])
    elif corruption == "input_pairing":
        rows[1]["potential_sha256"] = "wrong"
    elif corruption == "pair_class":
        rows[0]["per_pair"].pop()
    else:
        rows[0]["service_mode"] = "unknown"
    with pytest.raises(ValueError):
        audit.reconstruct_report(rows)


def test_undefined_paired_values_are_retained_not_zero_filled(observations):
    rows = deepcopy(observations)
    for row in rows:
        if row["arm"] == "QCAST-Slot" and row["seed"] == 7271:
            row["attempts_per_completion"] = None
            row["per_pair"][0]["completed_mean_latency"] = None
    report = audit.reconstruct_report(rows)
    contrast = next(row for row in report["paired_contrasts"] if row["kind"] == "qcast_vs_poqi")
    assert contrast["attempts_per_completion"]["n"] == 2
    assert contrast["attempts_per_completion"]["undefined"] == 1
    assert contrast["per_pair"][0]["completed_mean_latency"]["n"] == 2
    assert contrast["per_pair"][0]["completed_mean_latency"]["undefined"] == 1
    audit.close(report, producer.summarize(rows))


@pytest.fixture
def fake_native_inputs(tmp_path):
    build = tmp_path/"build"
    files = {"src/main/kotlin/Author.kt": b"author", "src/main/kotlin/poqi/qcast/SlotBridge.kt": b"bridge",
             "target/classes/Author.class": b"class", "dependency.jar": b"jar"}
    for name, content in files.items():
        path = build/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    dependency = build/"dependency.jar"
    (build/"classpath.txt").write_text(str(dependency))
    built = {"revision": audit.REVISION, "source_hashes": {"src/main/kotlin/Author.kt": audit.digest(build/"src/main/kotlin/Author.kt")},
             "bridge_sha256": audit.digest(build/"src/main/kotlin/poqi/qcast/SlotBridge.kt"),
             "dependency_hashes": {str(dependency): audit.digest(dependency)}}
    build_manifest = build.parent/"build-manifest.json"
    build_manifest.write_text(json.dumps(built), encoding="utf-8")
    return {"build": str(build), "native_inputs": {**{key: built[key] for key in ("source_hashes", "bridge_sha256", "dependency_hashes")},
             "build_manifest_sha256": audit.digest(build_manifest), "classpath_sha256": audit.digest(build/"classpath.txt"),
             "runtime_hashes": {str(Path("target/classes/Author.class")): audit.digest(build/"target/classes/Author.class")}}}


@pytest.mark.parametrize("target", ["src/main/kotlin/Author.kt", "src/main/kotlin/poqi/qcast/SlotBridge.kt",
                                    "target/classes/Author.class", "target/classes/Extra.class", "dependency.jar", "classpath.txt", "../build-manifest.json"])
def test_native_provenance_rejects_source_dependency_runtime_or_classpath_changes(fake_native_inputs, target):
    audit.verify_native_inputs(fake_native_inputs)
    path = Path(fake_native_inputs["build"])/target
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        audit.verify_native_inputs(fake_native_inputs)


@pytest.fixture
def partial_manifest(fake_native_inputs, records):
    directory = Path(fake_native_inputs["build"]).parent/"run"
    (directory/"runs").mkdir(parents=True)
    data = records[audit.ARMS[1], "fifo"]
    raw_path = directory/"runs/one.json.gz"
    raw_path.write_bytes(gzip.compress(json.dumps(data).encode()))
    entry = {"artifact": "runs/one.json.gz", "sha256": audit.digest(raw_path),
             **{field: data[field] for field in ("topology", "memory", "p", "seed", "arm", "service_mode", "workload_sha256", "potential_sha256")}}
    for name, content in {"observations.json": "[]", "report.json": "{}", "bridge-stderr.log": ""}.items():
        (directory/name).write_text(content, encoding="utf-8")
    manifest = {"status": "passed", "author_revision": audit.REVISION, "horizon": 40,
                "warmup": 10, "seeds": [7271], "arms": list(audit.ARMS), "service_modes": list(audit.MODES),
                "topologies": ["diamond"], "capacities": [2, 4], "probabilities": [1., .5],
                "source_hashes": {name: audit.digest(audit.ROOT/name) for name in audit.SOURCE_FILES},
                "runs": [entry], "artifact_hashes": {name: audit.digest(directory/name) for name in ("observations.json", "report.json", "bridge-stderr.log")},
                **fake_native_inputs}
    return directory, manifest


@pytest.mark.parametrize("corruption,message", [
    ("missing_runs", "missing/extra trajectories"), ("duplicate_raw", "duplicate/outside raw artifact"),
    ("metadata", "run metadata"), ("raw_changed", "raw artifact changed"),
    ("report_changed", "saved artifact changed"), ("missing_source", "source provenance inventory"),
    ("source_changed", "source changed since run"), ("missing_mode", "manifest service modes"),
    ("missing_artifact_digest", "artifact provenance inventory"), ("seed_reuse", "invalid manifest seeds"),
])
def test_manifest_completeness_identity_and_hashes(partial_manifest, corruption, message):
    directory, manifest = partial_manifest
    if corruption == "duplicate_raw":
        manifest["runs"].append(deepcopy(manifest["runs"][0]))
    elif corruption == "metadata":
        manifest["runs"][0]["seed"] += 1
    elif corruption == "raw_changed":
        (directory/manifest["runs"][0]["artifact"]).write_bytes(b"changed")
    elif corruption == "report_changed":
        (directory/"report.json").write_text("changed")
    elif corruption == "missing_source":
        manifest["source_hashes"].pop("scripts/qcast_concurrent.py")
    elif corruption == "source_changed":
        manifest["source_hashes"]["scripts/qcast_concurrent.py"] = "changed"
    elif corruption == "missing_mode":
        manifest["service_modes"].pop()
    elif corruption == "missing_artifact_digest":
        manifest["artifact_hashes"].pop("report.json")
    elif corruption == "seed_reuse":
        manifest["seeds"].append(manifest["seeds"][0])
    (directory/"manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        audit.audit(directory)


@pytest.mark.parametrize("corruption", ["missing_group", "missing_contrast", "wrong_contrast_mode", "pair_statistic", "zero_runs", "missing_metric"])
def test_computed_report_rejects_omitted_or_corrupted_summary_fields(observations, corruption):
    expected = audit.reconstruct_report(observations)
    report = deepcopy(expected)
    if corruption == "missing_group":
        report["summaries"].pop()
    elif corruption == "missing_contrast":
        report["paired_contrasts"].pop()
    elif corruption == "wrong_contrast_mode":
        report["paired_contrasts"][0]["left_service_mode"] = "fifo"
    elif corruption == "pair_statistic":
        report["summaries"][0]["per_pair"][0]["completed"]["mean"] += 1
    elif corruption == "zero_runs":
        report["summaries"][0]["zero_service_runs"] += 1
    else:
        report["summaries"][0].pop("throughput")
    with pytest.raises(ValueError):
        audit.close(report, expected, "report")


@pytest.fixture(scope="module")
def native_records(tmp_path_factory):
    build = os.environ.get("QCAST_PILOT_BUILD")
    if not build:
        pytest.skip("set QCAST_PILOT_BUILD to the validated native bridge build")
    rows = []
    with pilot.NativeBridge(Path(build), tmp_path_factory.mktemp("concurrent-independent")/"bridge.log") as bridge:
        for mode in audit.MODES:
            rows.append(producer.run_trajectory("diamond", 4, .5, 7271, "QCAST-Slot", 40, bridge, mode))
    return rows


def test_native_physical_endpoint_replay_in_both_modes(native_records):
    for row in native_records:
        assert audit.replay(row) == len(row["completions"])
        audit.close(audit.observation(row, 10), producer.observe(row, 10))


@pytest.mark.parametrize("corruption", ["claimed_ebits", "swap_reuse", "omitted_service", "reset", "pair_omission", "flag_omission"])
def test_native_physical_corruption_is_rejected(native_records, corruption):
    data = deepcopy(native_records[1])
    if corruption == "claimed_ebits":
        data["slots"][0]["physical_ebits_available"] += 1
    elif corruption == "swap_reuse":
        row = next(row for row in data["slots"] if row["native"]["successful_swap_inputs"])
        row["native"]["successful_swap_inputs"].append(row["native"]["successful_swap_inputs"][0])
    elif corruption == "omitted_service":
        next(row for row in data["slots"] if row["end_completed"])["end_completed"] = []
    elif corruption == "reset":
        data["slots"][0]["native"]["reset_clean"] = False
    elif corruption == "pair_omission":
        data["slots"][0]["native"]["all_pairs"].pop()
    else:
        data["slots"][0]["native"]["post_p4_channels"].pop()
    with pytest.raises(ValueError):
        audit.replay(data)

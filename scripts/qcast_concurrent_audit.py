"""Independent physical and statistical audit of matched service-mode runs.

No runner, arm implementation, observer or summarizer is imported. A private
copy of the established independent physical replay supplies admission, origin
reservations, swaps, expiry, native endpoint traversal and resource accounting.
Only its service callback is replaced, without changing the old auditor module.
"""

import argparse
from collections import defaultdict
from contextvars import ContextVar
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL_AUDIT = ROOT / "scripts/qcast_pilot_audit.py"
_spec = importlib.util.spec_from_file_location("_qcast_concurrent_physical_audit", PHYSICAL_AUDIT)
_physical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_physical)
require, close, digest, ci = _physical.require, _physical.close, _physical.digest, _physical.ci
REVISION = "0a0251dd5f38eb1669ff6abe18ab83436ddbba18"
ARMS = ("QCAST-Slot", "POQI-Slot-balancing", "POQI-Slot-pressure_relaxed",
        "POQI-Persistent-balancing", "POQI-Persistent-pressure_relaxed",
        "POQI-Cutoff10-balancing", "POQI-Cutoff10-pressure_relaxed")
MODES = ("fifo", "concurrent_per_pair")
METRICS = ("completed", "throughput", "mean_backlog", "initial_backlog", "final_backlog",
           "backlog_growth", "completed_mean_latency", "unfinished_mean_age",
           "restricted_mean_wait_full_horizon", "attempts", "attempts_per_completion",
           "swaps", "swaps_per_completion", "allocated_qubits_mean", "stored_qubits_mean",
           "failed_attempts", "skipped_opportunities", "discarded_pairs", "expired_pairs")
PAIR_METRICS = ("completed", "throughput", "pending", "offered_total", "mean_backlog",
                "initial_backlog", "final_backlog", "backlog_growth", "completed_mean_latency",
                "unfinished_mean_age", "restricted_mean_wait_full_horizon")
SOURCE_FILES = {
    "scripts/qcast_concurrent.py", "scripts/qcast_pilot.py", "scripts/qcast_poqi.py",
    "scripts/qcast_reference.py", "QCAST_Concurrent_Protocol.md", "src/poqi/config.py",
    "src/poqi/simulation/sequence_adapter.py", "src/poqi/simulation/inventory.py",
    "scripts/qcast/SlotBridge.kt",
}
_mode = ContextVar("independent_qcast_service_mode", default=None)


def serve(pending, counts, ids, tick, requests, completions, live=None):
    """Replay service from available physical counts, never from saved IDs."""
    mode = _mode.get()
    require(mode in MODES, "unknown service_mode")
    require(all(type(value) is int and value >= 0 for value in counts.values()), "invalid physical pair count")
    require(len(pending) == len(set(pending)), "duplicate pending request")
    already = {row["id"] for row in completions}
    chosen, retained = [], []
    fifo_blocked = False
    for request_id in pending:
        request = requests[request_id]
        require(request["id"] == request_id and request_id not in already, "reused or wrong request identity")
        pair = tuple(request["pair"])
        available = counts.get(pair, 0) > 0
        if not available or (mode == "fifo" and fifo_blocked):
            retained.append(request_id)
            fifo_blocked = True
            continue
        require(request["arrival"] <= tick, "service before arrival")
        counts[pair] -= 1
        if live is not None:
            physical_id = _physical.oldest(live, pair)
            require(physical_id is not None, "service without a physical pair")
            del live[physical_id]
        chosen.append(request_id)
        completions.append({"id": request_id, "time": tick})
    pending.clear()
    pending.extend(retained)
    require(chosen == ids, f"{mode} service order/resource mismatch")


_physical.serve = serve


def replay(data):
    """Replay every phase with frozen physics and the declared demand service."""
    require(data.get("service_mode") in MODES, "unknown service_mode")
    require(data.get("arm") in ARMS, "unknown algorithm/storage arm")
    require(data.get("schema_version") == 1, "unknown trajectory schema")
    if data["arm"] == "QCAST-Slot":
        nodes = _physical.SPECS[data["topology"]][0]
        for row in data["slots"]:
            native = row["native"]
            require([item["pair"] for item in native["all_pairs"]] == [[a, b] for a in range(nodes) for b in range(a+1, nodes)],
                    "incomplete/duplicate native endpoint inventory")
            require([item["channel"] for item in native["post_p4_channels"]] == list(range(len(data["channels"]))),
                    "incomplete/duplicate native channel flags")
            require(sum(item["count"] for item in native["all_pairs"]) == native["total_remaining_pairs"],
                    "native all-pair total")
            require(row["physical_ebits_available"] == sum(item["count"] for item in native["delivered"]),
                    "native physical availability accounting")
    normalized = dict(data)
    if data["arm"] == "QCAST-Slot":
        normalized["arm"] = "QCAST-Slot-FIFO"  # old auditor's native dispatch label only
    token = _mode.set(data["service_mode"])
    try:
        return _physical.replay(normalized)
    finally:
        _mode.reset(token)


def pair_observation(requests, completions, horizon, warmup):
    """Chronological queue integration for one demand class, including hidden arrivals."""
    requests_by_id = {request["id"]: request for request in requests}
    departed = {}
    events = [(request["arrival"], 1) for request in requests]
    for completion in completions:
        identifier, when = completion["id"], completion["time"]
        require(identifier in requests_by_id and identifier not in departed, "unknown/reused completion")
        require(requests_by_id[identifier]["arrival"] <= when <= horizon, "completion outside request lifetime")
        departed[identifier] = when
        events.append((when, -1))
    events.sort()
    previous, backlog, area, full_area = 0, 0, 0., 0.
    for when, change in events + [(horizon, 0)]:
        full_area += backlog*(when-previous)
        area += backlog*max(0., when-max(previous, warmup))
        backlog += change
        require(backlog >= 0, "negative per-pair backlog")
        previous = when
    initial = sum(request["arrival"] <= warmup for request in requests)-sum(when <= warmup for when in departed.values())
    finished = [identifier for identifier, when in departed.items() if warmup < when <= horizon]
    unfinished = [identifier for identifier in requests_by_id if identifier not in departed]
    waits = [departed.get(identifier, horizon)-request["arrival"] for identifier, request in requests_by_id.items()]
    close(math.fsum(waits), full_area, "per-pair censored area")
    require(backlog == len(unfinished), "per-pair final queue")
    average = lambda values: math.fsum(values)/len(values) if values else None
    duration = horizon-warmup
    return {"completed": len(finished), "pending": backlog, "offered_total": len(requests),
            "throughput": len(finished)/duration, "zero_service": not finished,
            "mean_backlog": area/duration, "initial_backlog": initial,
            "final_backlog": backlog, "backlog_growth": (backlog-initial)/duration,
            "completed_mean_latency": average([departed[i]-requests_by_id[i]["arrival"] for i in finished]),
            "unfinished_mean_age": average([horizon-requests_by_id[i]["arrival"] for i in unfinished]),
            "restricted_mean_wait_full_horizon": average(waits)}


def observation(data, warmup):
    require(data.get("service_mode") in MODES, "unknown service_mode")
    require(type(warmup) is int and 0 <= warmup < data["horizon"], "invalid measurement window")
    observed = _physical.observation(data, warmup)
    observed["service_mode"] = data["service_mode"]
    pairs = []
    for pair in _physical.SPECS[data["topology"]][2]:
        requests = [request for request in data["requests"] if tuple(request["pair"]) == pair]
        identities = {request["id"] for request in requests}
        completions = [row for row in data["completions"] if row["id"] in identities]
        pairs.append({"pair": list(pair), **pair_observation(requests, completions, data["horizon"], warmup)})
    observed["per_pair"] = pairs
    for field in ("completed", "initial_backlog", "final_backlog", "throughput", "mean_backlog", "backlog_growth"):
        close(math.fsum(row[field] for row in pairs), observed[field], f"per-pair sum {field}")
    return observed


def reconstruct_report(observations):
    """Independently rebuild complete group and paired-seed interval records."""
    groups = {}
    for row in observations:
        key = tuple(row[field] for field in ("topology", "memory", "p", "arm", "service_mode"))
        require(key[3] in ARMS and key[4] in MODES, "unknown report arm/mode")
        indexed = groups.setdefault(key, {})
        require(row["seed"] not in indexed, "duplicate report seed")
        require([tuple(item["pair"]) for item in row["per_pair"]] == list(_physical.SPECS[key[0]][2]), "per-pair classes")
        indexed[row["seed"]] = row
    summaries = []
    for key, indexed in groups.items():
        rows = list(indexed.values())
        summary = dict(zip(("topology", "memory", "p", "arm", "service_mode"), key))
        summary.update({metric: ci([row[metric] for row in rows]) for metric in METRICS})
        summary.update(zero_service_runs=sum(row["zero_service"] for row in rows),
                       absorbing_runs=sum(row["absorbing_stall"] for row in rows),
                       native_accounting_discrepancy_slots=sum(row["native_accounting_discrepancy_slots"] for row in rows))
        summary["per_pair"] = [{"pair": list(pair),
                                "zero_service_runs": sum(row["per_pair"][index]["zero_service"] for row in rows),
                                **{metric: ci([row["per_pair"][index][metric] for row in rows]) for metric in PAIR_METRICS}}
                               for index, pair in enumerate(_physical.SPECS[key[0]][2])]
        summaries.append(summary)
    contrasts = []
    for condition in sorted({key[:3] for key in groups}):
        comparison_specs = [("qcast_vs_poqi", ARMS[0], arm, MODES[1], MODES[1]) for arm in ARMS[1:]]
        comparison_specs.extend(("service_mode", arm, arm, MODES[1], MODES[0]) for arm in ARMS)
        for base in (1, 3, 5):
            comparison_specs.extend(("pressure_vs_balancing", ARMS[base+1], ARMS[base], mode, mode) for mode in MODES)
        for kind, left, right, left_mode, right_mode in comparison_specs:
            left_key, right_key = (*condition, left, left_mode), (*condition, right, right_mode)
            require(left_key in groups and right_key in groups, "missing comparison arm/mode")
            a, b = groups[left_key], groups[right_key]
            require(a.keys() == b.keys(), "unpaired replicate seeds")
            for seed in a:
                require(all(a[seed][field] == b[seed][field] for field in ("workload_sha256", "potential_sha256")), "unmatched comparison inputs")
            def differences(metric, pair_index=None):
                values = []
                for seed in sorted(a):
                    x, y = a[seed], b[seed]
                    if pair_index is not None:
                        x, y = x["per_pair"][pair_index], y["per_pair"][pair_index]
                    values.append(None if x[metric] is None or y[metric] is None else x[metric]-y[metric])
                return ci(values)
            contrasts.append({"topology": condition[0], "memory": condition[1], "p": condition[2],
                              "kind": kind, "left": left, "right": right,
                              "left_service_mode": left_mode, "right_service_mode": right_mode,
                              **{metric: differences(metric) for metric in METRICS},
                              "per_pair": [{"pair": list(pair), **{metric: differences(metric, index) for metric in PAIR_METRICS}}
                                           for index, pair in enumerate(_physical.SPECS[condition[0]][2])]})
    return {"summaries": summaries, "paired_contrasts": contrasts}


def verify_native_inputs(manifest):
    build = Path(manifest["build"])
    build_manifest = build.parent / "build-manifest.json"
    recorded = manifest["native_inputs"]
    require(digest(build_manifest) == recorded["build_manifest_sha256"], "native build manifest changed")
    built = json.loads(build_manifest.read_text(encoding="utf-8"))
    require(built["revision"] == REVISION, "native build revision")
    for field in ("source_hashes", "dependency_hashes", "bridge_sha256"):
        close(built[field], recorded[field], f"native recorded {field}")
    for name, checksum in built["source_hashes"].items():
        require(digest(build/name) == checksum, f"staged author source changed: {name}")
    require(digest(build/"src/main/kotlin/poqi/qcast/SlotBridge.kt") == built["bridge_sha256"], "staged bridge changed")
    require(digest(build/"classpath.txt") == recorded["classpath_sha256"], "native classpath changed")
    dependencies = (build/"classpath.txt").read_text().strip().split(os.pathsep)
    require(set(dependencies) == set(built["dependency_hashes"]), "native dependency inventory changed")
    for path, checksum in built["dependency_hashes"].items():
        require(digest(path) == checksum, f"native dependency changed: {path}")
    runtime = {str(path.relative_to(build)): digest(path) for path in (build/"target/classes").rglob("*") if path.is_file()}
    require(bool(runtime), "compiled native classes missing")
    close(runtime, recorded["runtime_hashes"], "compiled native classes")


def audit(directory, historical=False):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "passed" and manifest["author_revision"] == REVISION, "incomplete or wrong-source run")
    close(manifest["arms"], list(ARMS), "manifest arms")
    close(manifest["service_modes"], list(MODES), "manifest service modes")
    close(manifest["topologies"], ["diamond"], "manifest topology")
    close(manifest["capacities"], [2, 4], "manifest capacities")
    close(manifest["probabilities"], [1., .5], "manifest probabilities")
    require(type(manifest["horizon"]) is int and type(manifest["warmup"]) is int
            and 0 <= manifest["warmup"] < manifest["horizon"] <= 2000, "invalid horizon/window")
    seeds = manifest["seeds"]
    require(seeds and len(seeds) == len(set(seeds)) and all(type(seed) is int and seed >= 0 for seed in seeds), "invalid manifest seeds")
    require({Path(name).as_posix() for name in manifest["source_hashes"]} == SOURCE_FILES,
            "source provenance inventory incomplete")
    current_matches = {name: digest(ROOT/name) == checksum for name, checksum in manifest["source_hashes"].items()}
    if not historical:
        require(all(current_matches.values()), "source changed since run; current-source validation unavailable")
    verify_native_inputs(manifest)
    require(set(manifest["artifact_hashes"]) == {"observations.json", "report.json", "bridge-stderr.log"}, "artifact provenance inventory incomplete")
    for name, checksum in manifest["artifact_hashes"].items():
        require(digest(directory/name) == checksum, f"saved artifact changed: {name}")
    observations, run_keys, paths, coupled = [], set(), set(), defaultdict(set)
    slot_count = completed_count = 0
    metadata = ("topology", "memory", "p", "seed", "arm", "service_mode", "workload_sha256", "potential_sha256")
    for entry in manifest["runs"]:
        path = (directory/entry["artifact"]).resolve()
        require(path.is_relative_to(directory/"runs") and path not in paths, "duplicate/outside raw artifact")
        paths.add(path)
        require(digest(path) == entry["sha256"], f"raw artifact changed: {path.name}")
        data = json.loads(gzip.decompress(path.read_bytes()))
        require(data["horizon"] == manifest["horizon"], "raw horizon mismatch")
        close({field: entry[field] for field in metadata}, {field: data[field] for field in metadata}, "run metadata")
        key = tuple(data[field] for field in metadata[:6])
        require(key not in run_keys, "duplicate trajectory")
        run_keys.add(key)
        completed_count += replay(data)
        slot_count += len(data["slots"])
        observations.append(observation(data, manifest["warmup"]))
        coupled[data["topology"], data["seed"]].add((data["workload_sha256"], data["potential_sha256"]))
    expected = {("diamond", capacity, probability, seed, arm, mode) for capacity in (2, 4)
                for probability in (1., .5) for seed in seeds for arm in ARMS for mode in MODES}
    require(run_keys == expected, "missing/extra trajectories")
    require(all(len(values) == 1 for values in coupled.values()), "cross-arm/mode/capacity/probability inputs differ")
    close(json.loads((directory/"observations.json").read_text(encoding="utf-8")), observations, "observations")
    rebuilt = reconstruct_report(observations)
    close(json.loads((directory/"report.json").read_text(encoding="utf-8")), rebuilt, "report")
    return {"status": "passed", "audit_sha256": digest(__file__), "physical_audit_sha256": digest(PHYSICAL_AUDIT),
            "manifest_sha256": digest(directory/"manifest.json"), "trajectories": len(observations),
            "slots_replayed": slot_count, "completed_requests_replayed": completed_count,
            "observation_fields_checked": sum(len(row) for row in observations),
            "per_pair_observations_checked": sum(len(row["per_pair"]) for row in observations),
            "summary_groups_checked": len(rebuilt["summaries"]), "paired_contrasts_checked": len(rebuilt["paired_contrasts"]),
            "zero_service_trajectories_retained": sum(row["zero_service"] for row in observations),
            "absorbing_trajectories_retained": sum(row["absorbing_stall"] for row in observations),
            "historical_mode": historical, "current_source_matches": current_matches,
            "raw_artifact_hashes_verified": len(paths), "native_runtime_hashes_verified": len(manifest["native_inputs"]["runtime_hashes"]),
            "main_protocol_grid": manifest["horizon"] == 400 and manifest["warmup"] == 100 and seeds == list(range(7271, 7281)),
            "method": "independent full physical replay with mode-aware service; chronological overall/per-pair queue integration; seed-paired statistics"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--historical", action="store_true", help="allow current-source differences; retain all build/artifact checks")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.directory, arguments.historical)
    output = arguments.output or arguments.directory/"independent-audit.json"
    require(output.resolve().is_relative_to(ROOT/"results"), "audit output must stay under results/")
    output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

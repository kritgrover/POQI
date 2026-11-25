"""Bounded, matched FIFO/concurrent-per-pair service experiment.

Routing, physical opportunities, POQI policies, and phase order are inherited
unchanged from qcast_pilot. The arm labels identify physical arms;
service_mode is always a separate mandatory dimension in saved trajectories.
"""

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys

try:
    from . import qcast_pilot as pilot
except ImportError:
    import qcast_pilot as pilot

ROOT, REVISION = pilot.ROOT, pilot.REVISION
ARMS = ("QCAST-Slot", *pilot.ARMS[1:])
# Preserve the frozen comparison grid while exposing the new policy to trajectory callers.
TRAJECTORY_ARMS = (*ARMS, "POQI-Slot-pressure_oriented", "POQI-Persistent-pressure_oriented",
                   "POQI-Cutoff10-pressure_oriented")
SERVICE_MODES = ("fifo", "concurrent_per_pair")
METRICS = ("completed", "throughput", "mean_backlog", "initial_backlog", "final_backlog",
           "backlog_growth", "completed_mean_latency", "unfinished_mean_age",
           "restricted_mean_wait_full_horizon", "attempts", "attempts_per_completion",
           "swaps", "swaps_per_completion", "allocated_qubits_mean", "stored_qubits_mean",
           "failed_attempts", "skipped_opportunities", "discarded_pairs", "expired_pairs")
PAIR_METRICS = ("completed", "throughput", "pending", "offered_total", "mean_backlog",
                "initial_backlog", "final_backlog", "backlog_growth", "completed_mean_latency",
                "unfinished_mean_age", "restricted_mean_wait_full_horizon")


def serve_requests(pending, counts, tick, completions, service_mode, consume=None):
    """Consume oldest requests within each pair; retain global order of the rest.

    In concurrent mode a missing pair cannot block a different pair. A physical
    consume callback is called exactly once per useful completion at either
    service phase; it never creates an ebit or changes routing/settlement.
    """
    if service_mode not in SERVICE_MODES:
        raise ValueError("unknown service_mode")
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("ebit counts must be nonnegative integers")
    if service_mode == "fifo":
        return pilot.serve_fifo(pending, counts, tick, completions, consume)
    retained, identifiers = deque(), []
    for request in pending:
        pair = tuple(request["pair"])
        if counts.get(pair, 0):
            if consume is not None and consume(pair, tick) is None:
                raise AssertionError("physical pair missing at service")
            counts[pair] -= 1
            identifiers.append(request["id"])
            completions.append({"id": request["id"], "time": tick})
        else:
            retained.append(request)
    pending.clear()
    pending.extend(retained)
    return identifiers


def audit_trajectory(data):
    """Fast accounting/service replay; the separate auditor replays physics."""
    mode = data["service_mode"]
    if mode not in SERVICE_MODES or data["arm"] not in TRAJECTORY_ARMS:
        raise ValueError("unknown arm or service mode")
    name, memory, seed, horizon = (data[k] for k in ("topology", "memory", "seed", "horizon"))
    graph, _, _, _, channels = pilot.specification(name)
    requests = data["requests"]
    if requests != pilot.workload(name, seed, horizon):
        raise ValueError("offered workload changed")
    if data["channels"] != [list(c) for c in channels] or len(data["slots"]) != horizon:
        raise ValueError("physical channels or slot count changed")
    if data["workload_sha256"] != hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest():
        raise ValueError("workload digest mismatch")
    digest, queue, cursor, completed, stock, inventory = hashlib.sha256(), deque(), 0, [], 0, []
    persistent = data["arm"].startswith(("POQI-Persistent", "POQI-Cutoff10"))
    for slot, row in enumerate(data["slots"]):
        if row["start"] != slot:
            raise ValueError("slot clock mismatch")
        while cursor < len(requests) and requests[cursor]["arrival"] <= slot:
            queue.append(requests[cursor])
            cursor += 1
        counts = Counter(tuple(pair["endpoints"]) for pair in inventory) if persistent else {}
        if serve_requests(queue, counts, slot, completed, mode) != row["start_completed"]:
            raise ValueError("start service mismatch")
        potential, _ = pilot.opportunities(name, seed, slot, channels)
        digest.update(json.dumps(potential, separators=(",", ":")).encode())
        selected, successes = row["selected"], row["successful"]
        if len(selected) != len(set(selected)) or any(i not in range(len(channels)) for i in selected):
            raise ValueError("physical opportunity reused or nonexistent")
        if successes != [i for i in selected if potential[i] < data["p"]]:
            raise ValueError("potential outcomes mismatch")
        if len(row["reserved_occupancy"]) != len(graph) or any(v < 0 or v > memory for v in row["reserved_occupancy"]):
            raise ValueError("physical memory limit exceeded")
        if row["qubit_time"] != sum(row["reserved_occupancy"]) or row["qubit_time"] != row["storage_qubit_time"] + 2*len(selected):
            raise ValueError("reserved qubit-time mismatch")
        if data["arm"] == ARMS[0]:
            native = row["native"]
            if not native["reset_clean"] or native["total_remaining_pairs"] != len(successes)-row["swaps"]:
                raise ValueError("native reset or physical inventory mismatch")
            counts = {tuple(item["pair"]): item["count"] for item in native["delivered"]}
        else:
            counts = Counter(tuple(pair["endpoints"]) for pair in row["settled"]["live_pairs"])
            inventory = row["final_inventory"]
            if row["remaining_pairs"] != len(inventory):
                raise ValueError("saved inventory mismatch")
        if serve_requests(queue, counts, slot+1, completed, mode) != row["end_completed"]:
            raise ValueError("end service mismatch")
        stock += len(successes)-row["swaps"]-row["expired_pairs"]-row["discarded_pairs"]
        stock -= len(row["start_completed"])+len(row["end_completed"])
        if stock != row["remaining_pairs"] or stock < 0:
            raise ValueError("pair conservation failed")
    queue.extend(requests[cursor:])
    if completed != data["completions"] or [r["id"] for r in queue] != data["pending"]:
        raise ValueError("completion or pending ledger mismatch")
    identifiers = [r["id"] for r in completed]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("request consumed twice")
    if digest.hexdigest() != data["potential_sha256"]:
        raise ValueError("potential digest mismatch")
    return True


def run_trajectory(name, memory, p, seed, arm_name, horizon, bridge, service_mode="concurrent_per_pair"):
    if service_mode not in SERVICE_MODES or arm_name not in TRAJECTORY_ARMS:
        raise ValueError("unknown arm or service mode")
    graph, _, _, _, channels = pilot.specification(name)
    arrivals = pilot.workload(name, seed, horizon)
    pending, completions, slots = deque(), [], []
    cursor = 0
    native = arm_name == ARMS[0]
    persistent = arm_name.startswith(("POQI-Persistent", "POQI-Cutoff10"))
    if native:
        ready = bridge.initialize(pilot.topology_text(name, memory, p))
        if ready["memory"] != [memory] * len(graph):
            raise AssertionError("native memory mismatch")
        arm = None
    else:
        policy = arm_name.rsplit("-", 1)[1]
        arm = pilot.PoqiOpportunityArm(graph, memory, policy, persistent,
                                 cutoff=10 if arm_name.startswith("POQI-Cutoff10") else None)
    ledger_digest = hashlib.sha256()
    for start in range(horizon):
        while cursor < len(arrivals) and arrivals[cursor]["arrival"] <= start:
            pending.append(arrivals[cursor])
            cursor += 1
        start_completed = serve_requests(pending, arm.ebit_counts(), start, completions, service_mode, arm.consume) if persistent else []
        active = sorted({tuple(r["pair"]) for r in pending})
        potential, order = pilot.opportunities(name, seed, start, channels)
        ledger_digest.update(json.dumps(potential, separators=(",", ":")).encode())
        outcomes = [u < p for u in potential]
        if native:
            response = bridge.slot(active, outcomes)
            selected = response["assigned"]
            successes = response["successful"]
            if successes != [i for i in selected if outcomes[i]]:
                raise AssertionError("native outcomes disagree with keyed opportunities")
            counts = {tuple(r["pair"]): r["count"] for r in response["delivered"]}
            before = response["total_remaining_pairs"]
            end_completed = serve_requests(pending, counts, start + 1, completions, service_mode)
            record = {"selected": selected, "successful": successes, "swaps": response["swaps"],
                      "qubit_time": 2 * len(selected), "storage_qubit_time": 0,
                      "reserved_occupancy": response["occupancy"], "blocked": None,
                      "expired_pairs": 0, "discarded_pairs": before-len(end_completed),
                      "remaining_pairs": 0, "physical_ebits_available": sum(r["count"] for r in response["delivered"]),
                      "native": response}
        else:
            allocation = arm.begin_slot(start, order)
            selected = allocation["selected"]
            successes = [identifier for identifier in selected if outcomes[identifier]]
            finished = arm.end_slot(start + 1, successes)
            end_completed = serve_requests(pending, arm.ebit_counts(), start + 1, completions, service_mode, arm.consume)
            final = arm.finish_slot(start + 1)
            record = {"selected": selected, "successful": successes, "swaps": finished["swaps"],
                      "qubit_time": allocation["qubit_time"], "storage_qubit_time": allocation["storage_qubit_time"],
                      "reserved_occupancy": allocation["reserved_occupancy"], "blocked": allocation["blocked"],
                      "expired_pairs": finished["expired_pairs"], "discarded_pairs": final["discarded_pairs"],
                      "remaining_pairs": final["remaining_pairs"], "allocation": allocation,
                      "settled": finished, "final_inventory": final["live_pairs"]}
        slots.append({"start": start, "start_completed": start_completed, "end_completed": end_completed, **record})
    pending.extend(arrivals[cursor:])  # includes all final-slot arrivals, even though not yet visible
    result = {"schema_version": 1, "service_mode": service_mode, "topology": name, "memory": memory, "p": p, "q": 1, "D": 1,
              "seed": seed, "arm": arm_name, "horizon": horizon, "channels": [list(c) for c in channels],
              "requests": arrivals, "completions": completions, "pending": [r["id"] for r in pending],
              "slots": slots, "potential_sha256": ledger_digest.hexdigest(),
              "workload_sha256": hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest()}
    audit_trajectory(result)
    return result



def observe(data, warmup):
    audit_trajectory(data)
    horizon = data["horizon"]
    if not 0 <= warmup < horizon:
        raise ValueError("invalid measurement window")
    duration = horizon - warmup
    finished = {r["id"]: r["time"] for r in data["completions"]}
    cohort = [r for r in data["requests"] if warmup < finished.get(r["id"], -1) <= horizon]
    latencies = [finished[r["id"]]-r["arrival"] for r in cohort]
    waits = [finished.get(r["id"], horizon)-r["arrival"] for r in data["requests"]]
    area = sum(max(0, finished.get(r["id"], horizon)-max(warmup, r["arrival"])) for r in data["requests"])
    qstart = sum(r["arrival"] <= warmup < finished.get(r["id"], horizon+1) for r in data["requests"])
    pending = [r for r in data["requests"] if r["id"] not in finished]
    slots = data["slots"][warmup:]
    attempts = sum(len(r["selected"]) for r in slots)
    swaps = sum(r["swaps"] for r in slots)
    done = len(cohort)
    last_inventory = data["slots"][-1].get("final_inventory", [])
    center_partners = {tuple(p["endpoints"]) for p in last_inventory}
    absorbing = (data["topology"] == "chain" and data["arm"].startswith("POQI-Persistent")
                 and bool(pending) and len(last_inventory) == data["memory"]
                 and center_partners in ({(0, 1)}, {(1, 2)}))
    per_pair = []
    for pair in pilot.specification(data["topology"])[3]:
        offered = [r for r in data["requests"] if tuple(r["pair"]) == pair]
        pair_cohort = [r for r in cohort if tuple(r["pair"]) == pair]
        pair_pending = [r for r in offered if r["id"] not in finished]
        pair_done = len(pair_cohort)
        pair_initial = sum(r["arrival"] <= warmup < finished.get(r["id"], horizon+1) for r in offered)
        pair_area = sum(max(0, finished.get(r["id"], horizon)-max(warmup, r["arrival"])) for r in offered)
        per_pair.append({"pair": list(pair), "completed": pair_done, "pending": len(pair_pending),
                         "offered_total": len(offered), "throughput": pair_done/duration,
                         "zero_service": pair_done == 0, "mean_backlog": pair_area/duration,
                         "initial_backlog": pair_initial, "final_backlog": len(pair_pending),
                         "backlog_growth": (len(pair_pending)-pair_initial)/duration,
                         "completed_mean_latency": statistics.mean(finished[r["id"]]-r["arrival"] for r in pair_cohort) if pair_cohort else None,
                         "unfinished_mean_age": statistics.mean(horizon-r["arrival"] for r in pair_pending) if pair_pending else None,
                         "restricted_mean_wait_full_horizon": statistics.mean(finished.get(r["id"], horizon)-r["arrival"] for r in offered) if offered else None})
    return {"topology": data["topology"], "memory": data["memory"], "p": data["p"],
            "service_mode": data["service_mode"], "seed": data["seed"], "arm": data["arm"], "completed": done, "throughput": done/duration,
            "mean_backlog": area/duration, "initial_backlog": qstart, "final_backlog": len(pending),
            "backlog_growth": (len(pending)-qstart)/duration,
            "completed_mean_latency": statistics.mean(latencies) if latencies else None,
            "unfinished_mean_age": statistics.mean(horizon-r["arrival"] for r in pending) if pending else None,
            "restricted_mean_wait_full_horizon": statistics.mean(waits) if waits else None,
            "attempts": attempts, "attempts_per_completion": attempts/done if done else None,
            "swaps": swaps, "swaps_per_completion": swaps/done if done else None,
            "allocated_qubits_mean": sum(r["qubit_time"] for r in slots)/duration,
            "stored_qubits_mean": sum(r["storage_qubit_time"] for r in slots)/duration,
            "failed_attempts": sum(len(r["selected"])-len(r["successful"]) for r in slots),
            "skipped_opportunities": len(data["channels"])*duration-attempts,
            "expired_pairs": sum(r["expired_pairs"] for r in slots),
            "discarded_pairs": sum(r["discarded_pairs"] for r in slots),
            "zero_service": done == 0, "absorbing_stall": absorbing,
            "native_accounting_discrepancy_slots": sum(bool(r.get("native", {}).get("author_accounting_discrepancy")) for r in slots),
            "per_pair": per_pair, "workload_sha256": data["workload_sha256"],
            "potential_sha256": data["potential_sha256"]}


def summarize(observations):
    """Seed-paired descriptive intervals; undefined ratios remain undefined."""
    groups = {}
    for row in observations:
        key = tuple(row[k] for k in ("topology", "memory", "p", "arm", "service_mode"))
        if key[3] not in ARMS or key[4] not in SERVICE_MODES:
            raise ValueError("unknown observation arm or service mode")
        group = groups.setdefault(key, {})
        if row["seed"] in group:
            raise ValueError("duplicate trajectory seed")
        group[row["seed"]] = row
    summaries = []
    for key, indexed in groups.items():
        rows = list(indexed.values())
        pairs = list(pilot.specification(key[0])[3])
        for row in rows:
            if [tuple(item["pair"]) for item in row["per_pair"]] != pairs:
                raise ValueError("per-pair observation classes mismatch")
        summaries.append({"topology": key[0], "memory": key[1], "p": key[2], "arm": key[3],
                          "service_mode": key[4], "zero_service_runs": sum(r["zero_service"] for r in rows),
                          "absorbing_runs": sum(r["absorbing_stall"] for r in rows),
                          "native_accounting_discrepancy_slots": sum(r["native_accounting_discrepancy_slots"] for r in rows),
                          **{metric: pilot.interval([r[metric] for r in rows]) for metric in METRICS},
                          "per_pair": [{"pair": list(pair),
                                        "zero_service_runs": sum(r["per_pair"][i]["zero_service"] for r in rows),
                                        **{metric: pilot.interval([r["per_pair"][i][metric] for r in rows]) for metric in PAIR_METRICS}}
                                       for i, pair in enumerate(pairs)]})
    contrasts = []
    for name, memory, p in sorted({key[:3] for key in groups}):
        comparisons = [("qcast_vs_poqi", ARMS[0], arm, "concurrent_per_pair", "concurrent_per_pair") for arm in ARMS[1:]]
        comparisons += [("service_mode", arm, arm, "concurrent_per_pair", "fifo") for arm in ARMS]
        comparisons += [("pressure_vs_balancing", ARMS[i+1], ARMS[i], mode, mode)
                        for i in (1, 3, 5) for mode in SERVICE_MODES]
        for kind, left, right, left_mode, right_mode in comparisons:
            keys = [(name, memory, p, left, left_mode), (name, memory, p, right, right_mode)]
            if any(key not in groups for key in keys):
                raise ValueError("paired arms or service modes missing")
            a, b = [groups[key] for key in keys]
            if a.keys() != b.keys():
                raise ValueError("paired seeds missing")
            for seed in a:
                if any(a[seed][k] != b[seed][k] for k in ("workload_sha256", "potential_sha256")):
                    raise ValueError("paired physical workload mismatch")
            def difference(metric, pair_index=None):
                values = []
                for seed in sorted(a):
                    x, y = a[seed], b[seed]
                    if pair_index is not None:
                        x, y = x["per_pair"][pair_index], y["per_pair"][pair_index]
                    values.append(None if x[metric] is None or y[metric] is None else x[metric]-y[metric])
                return pilot.interval(values)
            contrasts.append({"topology": name, "memory": memory, "p": p, "kind": kind,
                              "left": left, "right": right, "left_service_mode": left_mode,
                              "right_service_mode": right_mode,
                              **{metric: difference(metric) for metric in METRICS},
                              "per_pair": [{"pair": list(pair),
                                            **{metric: difference(metric, i) for metric in PAIR_METRICS}}
                                           for i, pair in enumerate(pilot.specification(name)[3])]})
    return {"summaries": summaries, "paired_contrasts": contrasts}


def verify_build(build):
    """Verify staged sources/dependencies and fingerprint actual runtime files."""
    build = Path(build).resolve()
    path = build.parent / "build-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["revision"] != REVISION or manifest["bridge_sha256"] != pilot.sha256(pilot.BRIDGE):
        raise ValueError("stale native bridge build")
    if pilot.sha256(build / "src/main/kotlin/poqi/qcast/SlotBridge.kt") != manifest["bridge_sha256"]:
        raise ValueError("staged bridge source changed")
    for name, digest in manifest["source_hashes"].items():
        if pilot.sha256(build / name) != digest:
            raise ValueError("staged author source changed")
    dependencies = (build / "classpath.txt").read_text().strip().split(os.pathsep)
    if set(dependencies) != set(manifest["dependency_hashes"]):
        raise ValueError("native dependency classpath changed")
    for name, digest in manifest["dependency_hashes"].items():
        if pilot.sha256(name) != digest:
            raise ValueError("native dependency changed")
    runtime = sorted((build / "target/classes").rglob("*"))
    runtime_hashes = {str(path.relative_to(build)): pilot.sha256(path) for path in runtime if path.is_file()}
    if not runtime_hashes:
        raise ValueError("compiled native classes missing")
    return {"build_manifest_sha256": pilot.sha256(path),
            "source_hashes": manifest["source_hashes"], "bridge_sha256": manifest["bridge_sha256"],
            "dependency_hashes": manifest["dependency_hashes"], "runtime_hashes": runtime_hashes,
            "classpath_sha256": pilot.sha256(build / "classpath.txt")}


def run_suite(output, horizon=400, warmup=100, seeds=range(7271, 7281), build=None):
    """Four diamond conditions, seven frozen arms, two service modes."""
    if type(horizon) is not int or type(warmup) is not int or not 0 <= warmup < horizon <= 2000:
        raise ValueError("concurrent pilot requires integer 0 <= warmup < horizon <= 2000")
    seeds = tuple(seeds)
    if not seeds or len(seeds) != len(set(seeds)) or any(type(s) is not int or s < 0 for s in seeds):
        raise ValueError("pilot seeds must be distinct nonnegative integers")
    output = Path(output).resolve()
    results = (ROOT / "results").resolve()
    if not output.is_relative_to(results) or output == results:
        raise ValueError("pilot output must be a new directory under results/")
    output.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), ROOT / "scripts/qcast_pilot.py", ROOT / "scripts/qcast_poqi.py",
                    ROOT / "scripts/qcast_reference.py", pilot.BRIDGE, ROOT / "QCAST_Concurrent_Protocol.md",
                    ROOT / "src/poqi/config.py", ROOT / "src/poqi/simulation/sequence_adapter.py",
                    ROOT / "src/poqi/simulation/inventory.py"]
    manifest = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                "author_revision": REVISION, "horizon": horizon, "warmup": warmup, "seeds": list(seeds),
                "python": sys.version,
                "root_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                                text=True, check=True, timeout=10).stdout.strip(),
                "arms": list(ARMS), "service_modes": list(SERVICE_MODES),
                "topologies": ["diamond"], "capacities": [2, 4], "probabilities": [1.0, 0.5],
                "source_hashes": {}, "runs": [], "artifact_hashes": {}}
    pilot.write_json(output / "manifest.json", manifest)
    try:
        manifest["source_hashes"] = {str(path.relative_to(ROOT)): pilot.sha256(path) for path in source_files}
        build = pilot.build_bridge(output) if build is None else Path(build).resolve()
        manifest["build"] = str(build)
        manifest["native_inputs"] = verify_build(build)
        (output / "runs").mkdir()
        observations = []
        with pilot.NativeBridge(build, output / "bridge-stderr.log") as bridge:
            for memory in (2, 4):
                for p in (1.0, 0.5):
                    for seed in seeds:
                        for arm in ARMS:
                            for mode in SERVICE_MODES:
                                record = run_trajectory("diamond", memory, p, seed, arm, horizon, bridge, mode)
                                observation = observe(record, warmup)
                                relative = f"runs/diamond-m{memory}-p{p}-{seed}-{arm}-{mode}.json.gz"
                                with gzip.open(output / relative, "wt", encoding="utf-8", compresslevel=1) as stream:
                                    json.dump(record, stream, separators=(",", ":"), allow_nan=False)
                                observations.append(observation)
                                manifest["runs"].append({"artifact": relative, "sha256": pilot.sha256(output / relative),
                                                         **{k: record[k] for k in ("topology", "memory", "p", "seed", "arm", "service_mode")},
                                                         "workload_sha256": record["workload_sha256"],
                                                         "potential_sha256": record["potential_sha256"]})
                        pilot.write_json(output / "manifest.json", manifest)
                    print(f"Validated diamond memory={memory} p={p}: {len(manifest['runs'])} trajectories", flush=True)
        pilot.write_json(output / "observations.json", observations)
        pilot.write_json(output / "report.json", summarize(observations))
        manifest["artifact_hashes"] = {name: pilot.sha256(output / name) for name in ("observations.json", "report.json", "bridge-stderr.log")}
        if any(pilot.sha256(ROOT / name) != digest for name, digest in manifest["source_hashes"].items()):
            raise ValueError("concurrent pilot inputs changed during run")
        if verify_build(build) != manifest["native_inputs"]:
            raise ValueError("native inputs changed during run")
        if any(pilot.sha256(output / row["artifact"]) != row["sha256"] for row in manifest["runs"]):
            raise ValueError("trajectory artifact changed during run")
        manifest["status"] = "passed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        pilot.write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--horizon", type=int, default=400)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7271)
    parser.add_argument("--build", type=Path)
    args = parser.parse_args()
    run_suite(args.output, args.horizon, args.warmup, range(args.seed, args.seed+args.replicates), args.build)


if __name__ == "__main__":
    main()


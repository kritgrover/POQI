"""Post-hoc demand-service diagnostic for one failed Q-CAST pilot condition.

Diamond, four qubits/node, p=.5, q=1, H=400, warm-up=100, ten paired seeds.
The condition was selected after observing FIFO zero service in the main pilot.
Only useful-consumption scheduling changes; native routing/reset is untouched.
This is a mechanism probe, not an additional prespecified performance arm.
"""

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import statistics

try:
    from . import qcast_pilot as pilot
except ImportError:
    import qcast_pilot as pilot


ROOT = pilot.ROOT
MODES = ("fifo", "concurrent_per_pair")
SEEDS = tuple(range(6271, 6281))
METRICS = ("throughput", "completed_mean_latency", "mean_backlog", "final_backlog",
           "backlog_growth", "unfinished_mean_age", "restricted_mean_wait_full_horizon",
           "attempts", "attempts_per_completion", "swaps", "swaps_per_completion",
           "allocated_qubits_mean", "failed_attempts", "discarded_pairs")


def consume_concurrent(pending, counts, tick, completions):
    """Consume oldest eligible requests within each pair, without global blocking."""
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("physical ebit counts must be nonnegative integers")
    retained, completed = deque(), []
    for request in pending:
        pair = tuple(request["pair"])
        if counts.get(pair, 0):
            counts[pair] -= 1
            completed.append(request["id"])
            completions.append({"id": request["id"], "time": tick})
        else:
            retained.append(request)
    pending.clear()
    pending.extend(retained)
    return completed


def run_concurrent(seed, horizon, bridge):
    """Same opportunity/visibility phases as the main native FIFO arm."""
    name, memory, p = "diamond", 4, .5
    graph, _, _, _, channels = pilot.specification(name)
    ready = bridge.initialize(pilot.topology_text(name, memory, p))
    if ready["memory"] != [memory] * len(graph):
        raise ValueError("native physical memory changed")
    arrivals = pilot.workload(name, seed, horizon)
    pending, completions, slots = deque(), [], []
    cursor = 0
    digest = hashlib.sha256()
    for start in range(horizon):
        while cursor < len(arrivals) and arrivals[cursor]["arrival"] <= start:
            pending.append(arrivals[cursor])
            cursor += 1
        active = sorted({tuple(r["pair"]) for r in pending})
        potential, _ = pilot.opportunities(name, seed, start, channels)
        digest.update(json.dumps(potential, separators=(",", ":")).encode())
        native = bridge.slot(active, [value < p for value in potential])
        counts = {tuple(row["pair"]): row["count"] for row in native["delivered"]}
        completed = consume_concurrent(pending, counts, start+1, completions)
        slots.append({
            "start": start, "start_completed": [], "end_completed": completed,
            "selected": native["assigned"], "successful": native["successful"],
            "swaps": native["swaps"], "qubit_time": 2*len(native["assigned"]),
            "storage_qubit_time": 0, "reserved_occupancy": native["occupancy"],
            "blocked": None, "expired_pairs": 0,
            "discarded_pairs": native["total_remaining_pairs"]-len(completed),
            "remaining_pairs": 0,
            "physical_ebits_available": sum(r["count"] for r in native["delivered"]),
            "native": native,
        })
    pending.extend(arrivals[cursor:])
    return {
        "schema_version": 1, "topology": name, "memory": memory, "p": p, "q": 1, "D": 1,
        "seed": seed, "arm": "QCAST-Slot-Concurrent-per-pair", "horizon": horizon,
        "channels": [list(c) for c in channels], "requests": arrivals,
        "completions": completions, "pending": [r["id"] for r in pending], "slots": slots,
        "potential_sha256": digest.hexdigest(),
        "workload_sha256": hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest(),
    }


def audit(data, mode):
    """Replay visibility and consumption without using either service function."""
    if mode not in MODES:
        raise ValueError("unknown service mode")
    name, seed, horizon = data["topology"], data["seed"], data["horizon"]
    graph, _, _, _, channels = pilot.specification(name)
    requests = data["requests"]
    if requests != pilot.workload(name, seed, horizon):
        raise ValueError("offered requests changed")
    if len(data["slots"]) != horizon:
        raise ValueError("missing slots")
    waiting, events, cursor = [], [], 0
    potential_digest = hashlib.sha256()
    for start, row in enumerate(data["slots"]):
        if row["start"] != start or row["start_completed"]:
            raise ValueError("native service must occur at slot end")
        while cursor < len(requests) and requests[cursor]["arrival"] <= start:
            waiting.append(cursor)
            cursor += 1
        active = sorted({tuple(requests[i]["pair"]) for i in waiting})
        native = row["native"]
        if [tuple(r["pair"]) for r in native["delivered"]] != active:
            raise ValueError("planner demand visibility mismatch")
        potential, _ = pilot.opportunities(name, seed, start, channels)
        potential_digest.update(json.dumps(potential, separators=(",", ":")).encode())
        selected, successful = row["selected"], row["successful"]
        if len(selected) != len(set(selected)) or any(i not in range(len(channels)) for i in selected):
            raise ValueError("reused or invalid channel opportunity")
        if successful != [i for i in selected if potential[i] < data["p"]]:
            raise ValueError("potential outcome mismatch")
        if selected != native["assigned"] or successful != native["successful"] or row["swaps"] != native["swaps"]:
            raise ValueError("slot and native records disagree")
        occupancy = [sum(node in channels[c][:2] for c in selected) for node in graph]
        if occupancy != native["occupancy"] or occupancy != row["reserved_occupancy"] or max(occupancy) > data["memory"]:
            raise ValueError("physical memory accounting failed")
        if row["qubit_time"] != 2*len(selected) or row["storage_qubit_time"] != 0:
            raise ValueError("qubit-time accounting failed")
        all_paths = [path for r in native["all_pairs"] for path in r["paths"]]
        used = [c for path in all_paths for c in path]
        if len(used) != len(set(used)) or sorted(used) != sorted(successful):
            raise ValueError("physical pairs overlap or omit successful channels")
        by_pair = {tuple(r["pair"]): r for r in native["all_pairs"]}
        for delivery in native["delivered"]:
            physical = by_pair[tuple(delivery["pair"])]
            if delivery["count"] != len(delivery["paths"]) or delivery["paths"] != physical["paths"]:
                raise ValueError("requested ebit count is not a physical output")
        if (not native["reset_clean"] or native["total_remaining_pairs"] != len(all_paths)
                or len(all_paths) != len(successful)-row["swaps"]):
            raise ValueError("physical pair conservation failed")
        budgets = {tuple(r["pair"]): len(r["paths"]) for r in native["delivered"]}
        chosen = []
        for identifier in waiting:
            pair = tuple(requests[identifier]["pair"])
            if budgets.get(pair, 0):
                budgets[pair] -= 1
                chosen.append(identifier)
            elif mode == "fifo":
                break
        if chosen != row["end_completed"]:
            raise ValueError("service scheduling or ebit consumption mismatch")
        events.extend({"id": identifier, "time": start+1} for identifier in chosen)
        chosen_set = set(chosen)
        waiting = [identifier for identifier in waiting if identifier not in chosen_set]
        if (row["discarded_pairs"] != len(all_paths)-len(chosen) or row["remaining_pairs"] != 0
                or row["expired_pairs"] != 0):
            raise ValueError("reset loss accounting failed")
    waiting.extend(range(cursor, len(requests)))
    if events != data["completions"] or waiting != data["pending"]:
        raise ValueError("completion or censored-request ledger mismatch")
    if potential_digest.hexdigest() != data["potential_sha256"]:
        raise ValueError("potential ledger hash mismatch")
    signature = hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest()
    if signature != data["workload_sha256"]:
        raise ValueError("workload signature mismatch")
    return True


def measure(data, mode, warmup):
    """Observe an audited record; retain censored requests and undefined ratios."""
    horizon = data["horizon"]
    if not 0 <= warmup < horizon:
        raise ValueError("invalid measurement window")
    duration = horizon-warmup
    requests = data["requests"]
    finished = {r["id"]: r["time"] for r in data["completions"]}
    cohort = [r for r in requests if warmup < finished.get(r["id"], -1) <= horizon]
    pending = [r for r in requests if r["id"] not in finished]
    waits = [finished.get(r["id"], horizon)-r["arrival"] for r in requests]
    area = sum(max(0, finished.get(r["id"], horizon)-max(warmup, r["arrival"])) for r in requests)
    initial = sum(r["arrival"] <= warmup < finished.get(r["id"], horizon+1) for r in requests)
    slots = data["slots"][warmup:]
    attempts, swaps = sum(len(r["selected"]) for r in slots), sum(r["swaps"] for r in slots)
    done = len(cohort)
    per_pair = []
    for pair in pilot.specification(data["topology"])[3]:
        completed = [r for r in cohort if tuple(r["pair"]) == pair]
        unfinished = [r for r in pending if tuple(r["pair"]) == pair]
        per_pair.append({"pair": list(pair), "completed": len(completed),
                         "throughput": len(completed)/duration, "pending": len(unfinished),
                         "offered_total": sum(tuple(r["pair"]) == pair for r in requests)})
    return {
        "seed": data["seed"], "mode": mode, "completed": done, "throughput": done/duration,
        "completed_mean_latency": statistics.mean(finished[r["id"]]-r["arrival"] for r in cohort) if cohort else None,
        "mean_backlog": area/duration, "initial_backlog": initial, "final_backlog": len(pending),
        "backlog_growth": (len(pending)-initial)/duration,
        "unfinished_mean_age": statistics.mean(horizon-r["arrival"] for r in pending) if pending else None,
        "restricted_mean_wait_full_horizon": statistics.mean(waits) if waits else None,
        "attempts": attempts, "attempts_per_completion": attempts/done if done else None,
        "swaps": swaps, "swaps_per_completion": swaps/done if done else None,
        "allocated_qubits_mean": sum(r["qubit_time"] for r in slots)/duration,
        "failed_attempts": sum(len(r["selected"])-len(r["successful"]) for r in slots),
        "discarded_pairs": sum(r["discarded_pairs"] for r in slots),
        "zero_service": done == 0,
        "native_accounting_discrepancy_slots": sum(r["native"]["author_accounting_discrepancy"] for r in slots),
        "per_pair": per_pair, "workload_sha256": data["workload_sha256"],
        "potential_sha256": data["potential_sha256"],
    }


def summarize(observations):
    groups = {mode: [r for r in observations if r["mode"] == mode] for mode in MODES}
    paired = {mode: {r["seed"]: r for r in rows} for mode, rows in groups.items()}
    if any(not rows or len(rows) != len(paired[mode]) for mode, rows in groups.items()):
        raise ValueError("missing or duplicate mode/seed observations")
    if paired[MODES[0]].keys() != paired[MODES[1]].keys():
        raise ValueError("paired seeds differ")
    for seed in paired[MODES[0]]:
        if any(paired[MODES[0]][seed][key] != paired[MODES[1]][seed][key]
               for key in ("workload_sha256", "potential_sha256")):
            raise ValueError("paired workloads or opportunities differ")
    summaries = []
    for mode, rows in groups.items():
        per_pair = []
        for pair in pilot.specification("diamond")[3]:
            values = [next(r for r in row["per_pair"] if tuple(r["pair"]) == pair) for row in rows]
            per_pair.append({"pair": list(pair), **{key: pilot.interval([r[key] for r in values])
                             for key in ("throughput", "completed", "pending", "offered_total")}})
        summaries.append({"mode": mode, "runs": len(rows), "zero_service_runs": sum(r["zero_service"] for r in rows),
                          "per_pair": per_pair, **{key: pilot.interval([r[key] for r in rows]) for key in METRICS}})
    differences = {}
    for key in METRICS:
        values = []
        for seed in paired[MODES[0]]:
            left, right = paired[MODES[1]][seed][key], paired[MODES[0]][seed][key]
            values.append(None if left is None or right is None else left-right)
        differences[key] = pilot.interval(values)
    return {"scope": "Post-hoc service-mechanism diagnostic, one condition selected after main FIFO failure",
            "summaries": summaries, "paired_concurrent_minus_fifo": differences}


def run_suite(output, main_directory, build):
    output, main_directory, build = (Path(p).resolve() for p in (output, main_directory, build))
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results":
        raise ValueError("diagnostic output must be a new directory under results/")
    main_manifest = json.loads((main_directory / "manifest.json").read_text())
    if main_manifest["status"] != "passed" or main_manifest["horizon"] != 400 or main_manifest["warmup"] != 100:
        raise ValueError("diagnostic requires the completed main pilot H400/warm-up100")
    native_manifest = json.loads((build.parent / "build-manifest.json").read_text())
    if native_manifest["revision"] != pilot.REVISION or native_manifest["bridge_sha256"] != pilot.sha256(pilot.BRIDGE):
        raise ValueError("native bridge revision or build changed")
    output.mkdir(parents=True, exist_ok=False)
    (output / "runs").mkdir()
    sources = [Path(__file__), ROOT / "scripts/qcast_pilot.py", pilot.BRIDGE]
    manifest = {
        "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "POST-HOC one-condition demand-service mechanism diagnostic; not a main pilot arm",
        "topology": "diamond", "memory": 4, "p": .5, "q": 1,
        "horizon": 400, "warmup": 100, "seeds": list(SEEDS), "modes": list(MODES),
        "source_hashes": {str(p.relative_to(ROOT)): pilot.sha256(p) for p in sources},
        "author_revision": pilot.REVISION, "build": str(build), "main_directory": str(main_directory),
        "main_manifest_sha256": pilot.sha256(main_directory / "manifest.json"), "runs": [],
    }
    pilot.write_json(output / "manifest.json", manifest)
    main_hashes = {r["artifact"]: r["sha256"] for r in main_manifest["runs"]}
    observations = []
    try:
        with pilot.NativeBridge(build, output / "bridge-stderr.log") as bridge:
            for seed in SEEDS:
                expected_file = f"runs/diamond-m4-p0.5-{seed}-QCAST-Slot-FIFO.json.gz"
                if pilot.sha256(main_directory / expected_file) != main_hashes[expected_file]:
                    raise ValueError("main reference trajectory hash changed")
                with gzip.open(main_directory / expected_file, "rt", encoding="utf-8") as stream:
                    expected = json.load(stream)
                fifo = pilot.run_trajectory("diamond", 4, .5, seed, pilot.ARMS[0], 400, bridge)
                if fifo != expected:
                    raise ValueError(f"FIFO replay does not exactly match main trajectory for seed {seed}")
                concurrent = run_concurrent(seed, 400, bridge)
                for mode, record in zip(MODES, (fifo, concurrent)):
                    audit(record, mode)
                    observation = measure(record, mode, 100)
                    if mode == "fifo":
                        original = pilot.observe(record, 100)
                        if any(observation[key] != original[key] for key in METRICS):
                            raise ValueError("independent FIFO measurements disagree with main observer")
                    observations.append(observation)
                    artifact = f"runs/{mode}-{seed}.json.gz"
                    with gzip.open(output / artifact, "wt", encoding="utf-8", compresslevel=1) as stream:
                        json.dump(record, stream, separators=(",", ":"), allow_nan=False)
                    manifest["runs"].append({"mode": mode, "seed": seed, "artifact": artifact,
                                             "sha256": pilot.sha256(output / artifact),
                                             "main_fifo_exact_replay": mode == "fifo"})
                pilot.write_json(output / "manifest.json", manifest)
                print(f"Validated service pair seed={seed}", flush=True)
        pilot.write_json(output / "observations.json", observations)
        pilot.write_json(output / "report.json", summarize(observations))
        if any(pilot.sha256(ROOT / name) != digest for name, digest in manifest["source_hashes"].items()):
            raise ValueError("diagnostic source changed during run")
        manifest["status"] = "passed"
        manifest["artifact_hashes"] = {name: pilot.sha256(output / name) for name in ("observations.json", "report.json")}
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
    parser.add_argument("--main", type=Path, default=ROOT / "results/qcast/pilot-main-01")
    parser.add_argument("--build", type=Path, default=ROOT / "results/qcast/pilot-smoke-01/build")
    args = parser.parse_args()
    run_suite(args.output, args.main, args.build)


if __name__ == "__main__":
    main()

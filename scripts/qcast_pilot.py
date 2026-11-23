"""Bounded matched-opportunity Q-CAST/POQI system pilot (not Q-CAST-PI).

All policies see identical physical opportunities and request arrivals. The
author routing algorithm runs in a headless JVM; POQI uses unchanged root swap
helpers in explicitly labelled slot/persistent opportunity wrappers.
"""

import argparse
import base64
from collections import Counter, deque
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import shutil
import statistics
import subprocess
import sys
import threading

import networkx as nx
from scipy.stats import t as student_t

try:
    from .qcast_reference import ROOT, REVISION, sha256, verify_source
    from .qcast_poqi import PoqiOpportunityArm
except ImportError:
    from qcast_reference import ROOT, REVISION, sha256, verify_source
    from qcast_poqi import PoqiOpportunityArm


BRIDGE = ROOT / "scripts/qcast/SlotBridge.kt"
ARMS = ("QCAST-Slot-FIFO", "POQI-Slot-balancing", "POQI-Slot-pressure_relaxed",
        "POQI-Persistent-balancing", "POQI-Persistent-pressure_relaxed",
        "POQI-Cutoff10-balancing", "POQI-Cutoff10-pressure_relaxed")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def keyed_uniform(seed, topology, namespace, *identity):
    """Stable potential outcome; no policy name, capacity, or action counter."""
    encoded = json.dumps([seed, topology, namespace, *identity], separators=(",", ":")).encode()
    bits = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") >> 11
    return bits / (1 << 53)  # [0,1): p=1 always succeeds; p=0 always fails


def specification(name):
    graph = nx.Graph()
    if name == "chain":
        locations = [(0, 0), (1, 0), (2, 0)]
        edges = [(0, 1), (1, 2)]
        demand = {(0, 2): 0.75}
    elif name == "diamond":
        locations = [(0, 0), (1, 0), (0, 1), (1, 1)]
        edges = [(0, 1), (0, 2), (1, 3), (2, 3)]
        demand = {(0, 3): 0.5, (0, 1): 0.25, (1, 2): 0.15}
    else:
        raise ValueError("unknown pilot topology")
    graph.add_nodes_from(range(len(locations)))
    graph.add_edges_from(edges, generation_capacity=1.0)
    channels = [(u, v, i * 2 + lane) for i, (u, v) in enumerate(edges) for lane in range(2)]
    return graph, locations, edges, demand, channels


def topology_text(name, memory, p):
    graph, locations, edges, _, _ = specification(name)
    return "\n".join([str(len(graph)), str(-math.log(p)), "1.0", "1"] +
                     [f"{memory} {x}.0 {y}.0" for x, y in locations] +
                     [f"{u} {v} 2" for u, v in edges])


def workload(name, seed, horizon):
    _, _, _, demands, _ = specification(name)
    arrivals = []
    for pair, rate in demands.items():
        seed_data = json.dumps([seed, name, "requests", *pair]).encode()
        rng = random.Random(int.from_bytes(hashlib.sha256(seed_data).digest(), "big"))
        moment = rng.expovariate(rate)
        while moment < horizon:
            arrivals.append({"pair": list(pair), "arrival": moment})
            moment += rng.expovariate(rate)
    arrivals.sort(key=lambda r: (r["arrival"], r["pair"]))
    return [{"id": i, **row} for i, row in enumerate(arrivals)]


def opportunities(name, seed, slot, channels):
    potential = [keyed_uniform(seed, name, "link", slot, u, v, identifier % 2)
                 for u, v, identifier in channels]
    order = sorted(channels, key=lambda c: keyed_uniform(seed, name, "ordering", slot, *c))
    return potential, order


def build_bridge(output, source=None, maven=None):
    """Compile tracked, pinned author inputs plus this bridge, offline."""
    source = Path(source or ROOT / "results/qcast/QuantumRouting").resolve()
    maven = Path(maven or ROOT / "results/qcast/tools/apache-maven-3.9.9/bin/mvn.cmd").resolve()
    hashes = verify_source(source)
    build = Path(output).resolve() / "build"
    build.mkdir(parents=True, exist_ok=False)
    for name in hashes:
        destination = build / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    destination = build / "src/main/kotlin/poqi/qcast/SlotBridge.kt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BRIDGE, destination)
    cp = build / "classpath.txt"
    command = [str(maven), "-B", "-o", "-f", str(build / "pom.xml"),
               f"-Dmaven.repo.local={ROOT / 'results/qcast/m2'}", "compile",
               "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:build-classpath",
               f"-Dmdep.outputFile={cp}"]
    with (Path(output) / "build.log").open("wb") as log:
        subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if verify_source(source) != hashes or any(sha256(build / name) != digest for name, digest in hashes.items()):
        raise ValueError("author sources changed during build")
    write_json(Path(output) / "build-manifest.json", {
        "revision": REVISION, "source_hashes": hashes, "bridge_sha256": sha256(BRIDGE),
        "command": command, "dependency_hashes": {p: sha256(p) for p in cp.read_text().strip().split(os.pathsep)},
    })
    return build


class NativeBridge:
    """One bounded-response JVM session; no interactive GUI or figure pipeline."""

    def __init__(self, build, log_path):
        build = Path(build).resolve()
        self.log = Path(log_path).open("w", encoding="utf-8")
        self.process = subprocess.Popen([
            "java", "-Djava.awt.headless=true", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
            "-ea", "-cp", str(build / "target/classes") + os.pathsep +
            (build / "classpath.txt").read_text().strip(), "poqi.qcast.SlotBridge"],
            cwd=build, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding="utf-8", bufsize=1)
        self.replies = queue.Queue()
        def read_lines():
            for line in self.process.stdout:
                self.replies.put(line)
            self.replies.put(None)
        self.reader = threading.Thread(target=read_lines, daemon=True)
        self.reader.start()

    def exchange(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        try:
            reply = self.replies.get(timeout=10)
        except queue.Empty as error:
            raise RuntimeError("Q-CAST bridge response timed out (10 seconds)") from error
        if reply is None:
            raise RuntimeError("Q-CAST bridge exited; inspect bridge stderr")
        result = json.loads(reply)
        if "error" in result:
            raise RuntimeError(f"Q-CAST bridge error: {result['error']}")
        return result

    def initialize(self, config, recovery=True):
        return self.exchange("INIT\t" + base64.b64encode(config.encode()).decode() + "\t" + str(recovery).lower())

    def slot(self, pairs, outcomes):
        requests = ";".join(f"{u},{v}" for u, v in pairs)
        return self.exchange("SLOT\t" + requests + "\t" + "".join("1" if b else "0" for b in outcomes))

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("EXIT\n")
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.reader.join(timeout=1)
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def serve_fifo(pending, counts, tick, completions, consume=None):
    """No bypass: one physical ebit completes at most one oldest unit request."""
    completed = []
    while pending:
        request = pending[0]
        pair = tuple(request["pair"])
        if counts.get(pair, 0) == 0:
            break
        if consume is not None and consume(pair, tick) is None:
            raise AssertionError("service observer and physical inventory disagree")
        counts[pair] -= 1
        pending.popleft()
        event = {"id": request["id"], "time": tick}
        completions.append(event)
        completed.append(request["id"])
    return completed


def run_trajectory(name, memory, p, seed, arm_name, horizon, bridge):
    graph, _, _, _, channels = specification(name)
    arrivals = workload(name, seed, horizon)
    pending, completions, slots = deque(), [], []
    cursor = 0
    native = arm_name == ARMS[0]
    persistent = arm_name.startswith(("POQI-Persistent", "POQI-Cutoff10"))
    if native:
        ready = bridge.initialize(topology_text(name, memory, p))
        if ready["memory"] != [memory] * len(graph):
            raise AssertionError("native memory mismatch")
        arm = None
    else:
        policy = arm_name.rsplit("-", 1)[1]
        arm = PoqiOpportunityArm(graph, memory, policy, persistent,
                                 cutoff=10 if arm_name.startswith("POQI-Cutoff10") else None)
    ledger_digest = hashlib.sha256()
    for start in range(horizon):
        while cursor < len(arrivals) and arrivals[cursor]["arrival"] <= start:
            pending.append(arrivals[cursor])
            cursor += 1
        start_completed = serve_fifo(pending, arm.ebit_counts(), start, completions, arm.consume) if persistent else []
        active = sorted({tuple(r["pair"]) for r in pending})
        potential, order = opportunities(name, seed, start, channels)
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
            end_completed = serve_fifo(pending, counts, start + 1, completions)
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
            end_completed = serve_fifo(pending, arm.ebit_counts(), start + 1, completions, arm.consume)
            final = arm.finish_slot(start + 1)
            record = {"selected": selected, "successful": successes, "swaps": finished["swaps"],
                      "qubit_time": allocation["qubit_time"], "storage_qubit_time": allocation["storage_qubit_time"],
                      "reserved_occupancy": allocation["reserved_occupancy"], "blocked": allocation["blocked"],
                      "expired_pairs": finished["expired_pairs"], "discarded_pairs": final["discarded_pairs"],
                      "remaining_pairs": final["remaining_pairs"], "allocation": allocation,
                      "settled": finished, "final_inventory": final["live_pairs"]}
        slots.append({"start": start, "start_completed": start_completed, "end_completed": end_completed, **record})
    pending.extend(arrivals[cursor:])  # includes all final-slot arrivals, even though not yet visible
    result = {"schema_version": 1, "topology": name, "memory": memory, "p": p, "q": 1, "D": 1,
              "seed": seed, "arm": arm_name, "horizon": horizon, "channels": [list(c) for c in channels],
              "requests": arrivals, "completions": completions, "pending": [r["id"] for r in pending],
              "slots": slots, "potential_sha256": ledger_digest.hexdigest(),
              "workload_sha256": hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest()}
    audit_trajectory(result)
    return result


def audit_trajectory(data):
    """Independent workload/opportunity accounting, including retained zero runs."""
    name, memory, seed, horizon = (data[key] for key in ("topology", "memory", "seed", "horizon"))
    graph, _, _, _, channels = specification(name)
    requests = data["requests"]
    if requests != workload(name, seed, horizon):
        raise ValueError("offered workload changed")
    completed = data["completions"]
    ids = [r["id"] for r in completed]
    if ids != list(range(len(ids))) or data["pending"] != list(range(len(ids), len(requests))):
        raise ValueError("global FIFO or outstanding-request accounting failed")
    if any(r["time"] < math.ceil(requests[r["id"]]["arrival"]) or r["time"] > horizon for r in completed):
        raise ValueError("ineligible or out-of-window service")
    if [r["time"] for r in completed] != sorted(r["time"] for r in completed):
        raise ValueError("completion clock reversed")
    if len(data["slots"]) != horizon:
        raise ValueError("missing slots")
    stock = 0
    event_completions = []
    for slot, row in enumerate(data["slots"]):
        if row["start"] != slot:
            raise ValueError("slot clock mismatch")
        potential, _ = opportunities(name, seed, slot, channels)
        selected, successes = row["selected"], row["successful"]
        if len(selected) != len(set(selected)) or any(i not in range(len(channels)) for i in selected):
            raise ValueError("physical opportunity reused or nonexistent")
        if successes != [i for i in selected if potential[i] < data["p"]]:
            raise ValueError("potential outcomes mismatch")
        if len(row["reserved_occupancy"]) != len(graph) or any(v < 0 or v > memory for v in row["reserved_occupancy"]):
            raise ValueError("physical memory limit exceeded")
        if row["qubit_time"] != sum(row["reserved_occupancy"]) or row["qubit_time"] != row["storage_qubit_time"] + 2*len(selected):
            raise ValueError("reserved qubit-time mismatch")
        for phase, tick in (("start_completed", slot), ("end_completed", slot+1)):
            event_completions.extend({"id": identifier, "time": tick} for identifier in row[phase])
        stock += len(successes) - row["swaps"] - row["expired_pairs"] - row["discarded_pairs"]
        stock -= len(row["start_completed"]) + len(row["end_completed"])
        if stock != row["remaining_pairs"] or stock < 0:
            raise ValueError("pair conservation failed")
        if data["arm"] == ARMS[0]:
            native = row["native"]
            if not native["reset_clean"] or native["total_remaining_pairs"] != len(successes)-row["swaps"]:
                raise ValueError("native reset or physical inventory mismatch")
        elif row["remaining_pairs"] != len(row["final_inventory"]):
            raise ValueError("saved inventory mismatch")
    if event_completions != completed:
        raise ValueError("slot completion ledger mismatch")
    return True


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
    for pair in specification(data["topology"])[3]:
        offered = [r for r in data["requests"] if tuple(r["pair"]) == pair]
        per_pair.append({"pair": list(pair), "completed": sum(tuple(r["pair"]) == pair for r in cohort),
                         "pending": sum(r["id"] not in finished for r in offered),
                         "offered_total": len(offered)})
    return {"topology": data["topology"], "memory": data["memory"], "p": data["p"],
            "seed": data["seed"], "arm": data["arm"], "completed": done, "throughput": done/duration,
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


def interval(values):
    defined = [v for v in values if v is not None]
    if not defined:
        return {"mean": None, "low": None, "high": None, "n": 0, "undefined": len(values)}
    mean = statistics.mean(defined)
    half = student_t.ppf(.975, len(defined)-1)*statistics.stdev(defined)/math.sqrt(len(defined)) if len(defined)>1 else None
    return {"mean": mean, "low": None if half is None else mean-half, "high": None if half is None else mean+half,
            "n": len(defined), "undefined": len(values)-len(defined)}


def summarize(observations):
    groups = {}
    for row in observations:
        groups.setdefault((row["topology"], row["memory"], row["p"], row["arm"]), []).append(row)
    metrics = ("throughput", "mean_backlog", "final_backlog", "backlog_growth", "completed_mean_latency",
               "unfinished_mean_age", "restricted_mean_wait_full_horizon", "attempts_per_completion",
               "swaps_per_completion", "allocated_qubits_mean", "stored_qubits_mean", "failed_attempts",
               "skipped_opportunities", "discarded_pairs", "expired_pairs")
    summaries = [{"topology": key[0], "memory": key[1], "p": key[2], "arm": key[3],
                  "zero_service_runs": sum(r["zero_service"] for r in rows),
                  "absorbing_runs": sum(r["absorbing_stall"] for r in rows),
                  "native_accounting_discrepancy_slots": sum(r["native_accounting_discrepancy_slots"] for r in rows),
                  **{metric: interval([r[metric] for r in rows]) for metric in metrics}}
                 for key, rows in groups.items()]
    contrasts = []
    for name, memory, p in sorted({key[:3] for key in groups}):
        pairs = [(ARMS[0], arm) for arm in ARMS[1:]] + [(ARMS[2], ARMS[1]), (ARMS[4], ARMS[3]), (ARMS[6], ARMS[5])]
        for left, right in pairs:
            a, b = [{r["seed"]: r for r in groups[name, memory, p, arm]} for arm in (left, right)]
            if a.keys() != b.keys():
                raise ValueError("paired seeds missing")
            for seed in a:
                if any(a[seed][k] != b[seed][k] for k in ("workload_sha256", "potential_sha256")):
                    raise ValueError("paired physical workload mismatch")
            contrasts.append({"topology": name, "memory": memory, "p": p, "left": left, "right": right,
                              **{metric: interval([a[s][metric]-b[s][metric] for s in a])
                                 for metric in ("throughput", "mean_backlog", "allocated_qubits_mean")}})
    return {"summaries": summaries, "paired_contrasts": contrasts}


def run_suite(output, horizon=400, warmup=100, seeds=range(6271, 6281), build=None):
    if (type(horizon) is not int or type(warmup) is not int or not 0 <= warmup < horizon <= 2000):
        raise ValueError("pilot requires integer 0 <= warmup < horizon <= 2000")
    seeds = tuple(seeds)
    if not seeds or len(seeds) != len(set(seeds)) or any(type(s) is not int or s < 0 for s in seeds):
        raise ValueError("pilot seeds must be distinct nonnegative integers")
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results":
        raise ValueError("pilot output must be a new directory under results/")
    output.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), ROOT / "scripts/qcast_poqi.py", ROOT / "scripts/qcast_reference.py",
                    BRIDGE, ROOT / "QCAST_Pilot_Protocol.md",
                    ROOT / "src/poqi/simulation/sequence_adapter.py", ROOT / "src/poqi/simulation/inventory.py"]
    manifest = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                "author_revision": REVISION, "horizon": horizon, "warmup": warmup, "seeds": list(seeds),
                "python": sys.version,
                "root_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                                text=True, check=True, timeout=10).stdout.strip(),
                "arms": list(ARMS), "source_hashes": {str(p.relative_to(ROOT)): sha256(p) for p in source_files},
                "runs": []}
    write_json(output / "manifest.json", manifest)
    try:
        build = build_bridge(output) if build is None else Path(build).resolve()
        manifest["build"] = str(build)
        build_manifest = json.loads((build.parent / "build-manifest.json").read_text())
        if build_manifest["revision"] != REVISION or build_manifest["bridge_sha256"] != sha256(BRIDGE):
            raise ValueError("stale native bridge build")
        (output / "runs").mkdir()
        observations = []
        with NativeBridge(build, output / "bridge-stderr.log") as bridge:
            for name, capacities in (("chain", (2, 3, 4)), ("diamond", (2, 4))):
                for memory in capacities:
                    for p in (1.0, 0.5):
                        for seed in seeds:
                            for arm in ARMS:
                                record = run_trajectory(name, memory, p, seed, arm, horizon, bridge)
                                observation = observe(record, warmup)
                                relative = f"runs/{name}-m{memory}-p{p}-{seed}-{arm}.json.gz"
                                with gzip.open(output / relative, "wt", encoding="utf-8", compresslevel=1) as stream:
                                    json.dump(record, stream, separators=(",", ":"), allow_nan=False)
                                observations.append(observation)
                                manifest["runs"].append({"artifact": relative, "sha256": sha256(output / relative)})
                        write_json(output / "manifest.json", manifest)
                        print(f"Validated {name} memory={memory} p={p}: {len(manifest['runs'])} trajectories", flush=True)
        write_json(output / "observations.json", observations)
        write_json(output / "report.json", summarize(observations))
        if any(sha256(ROOT / name) != digest for name, digest in manifest["source_hashes"].items()):
            raise ValueError("pilot inputs changed during run")
        manifest["status"] = "passed"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--horizon", type=int, default=400)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--seed", type=int, default=6271)
    parser.add_argument("--build", type=Path)
    args = parser.parse_args()
    run_suite(args.output, args.horizon, args.warmup, range(args.seed, args.seed+args.replicates), args.build)


if __name__ == "__main__":
    main()

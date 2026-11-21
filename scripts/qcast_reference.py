"""Build and run small cases against the pinned, unmodified Q-CAST sources.

This is a reference runner and independent metric oracle, not a routing policy.
Download the public checkout and Maven separately; this script never installs
software, clones repositories, or invokes the authors' figure-generation entry
points. All generated files must stay under the root ignored results directory.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REVISION = "0a0251dd5f38eb1669ff6abe18ab83436ddbba18"
AUTHOR_URL = "https://github.com/sshi27/QuantumRouting"
DRIVER = ROOT / "scripts/qcast/ReferenceValidation.kt"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_yield(probabilities, width, swap_probability):
    """Independent exhaustive expectation of min(edge successes)*q**(h-1).

    Deliberately small-case only. Enumerates independent binomial counts rather
    than reproducing Topo.e's incremental recurrence. No recovery contribution.
    """
    probabilities = tuple(probabilities)
    if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 8:
        raise ValueError("oracle width must be an integer in 1..8")
    if not 1 <= len(probabilities) <= 6:
        raise ValueError("oracle requires 1..6 edges")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or
           not math.isfinite(p) or not 0 <= p <= 1
           for p in (*probabilities, swap_probability)):
        raise ValueError("probabilities must be finite numbers in [0,1]")
    pmfs = [[math.comb(width, k) * p**k * (1-p)**(width-k)
             for k in range(width+1)] for p in probabilities]
    expectation = math.fsum(
        min(counts) * math.prod(pmf[k] for pmf, k in zip(pmfs, counts))
        for counts in itertools.product(range(width+1), repeat=len(pmfs)))
    return expectation * swap_probability**(len(probabilities)-1)


def _git(source, *args):
    return subprocess.run(["git", "-C", str(source), *args], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def verify_source(source):
    source = Path(source).resolve()
    if _git(source, "rev-parse", "HEAD") != REVISION:
        raise ValueError(f"reference must be pinned to {REVISION}")
    if _git(source, "diff", "HEAD", "--", "pom.xml", "src/main/kotlin"):
        raise ValueError("authors' build/routing sources have local changes")
    names = _git(source, "ls-files", "pom.xml", "src/main/kotlin").splitlines()
    if "pom.xml" not in names or not any(n.endswith("OnlineAlgorithm.kt") for n in names):
        raise ValueError("incomplete author checkout")
    return {name: sha256(source / name) for name in names}


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run_reference(source, maven, output, *, offline=True, java="java"):
    source, maven, output = map(lambda p: Path(p).resolve(), (source, maven, output))
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results":
        raise ValueError("output must be a new directory under results/")
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("source checkout and output must be separate")
    source_hashes = verify_source(source)
    if not maven.is_file():
        raise ValueError("Maven executable does not exist")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1, "status": "running", "author_repository": AUTHOR_URL,
        "author_revision": REVISION, "source_hashes": source_hashes,
        "driver_sha256": sha256(DRIVER), "runner_sha256": sha256(__file__),
        "root_revision": _git(ROOT, "rev-parse", "HEAD"),
        "utc_started": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "offline": offline, "commands": [],
    }
    _write_json(output / "manifest.json", manifest)

    def execute(args, log, cwd, timeout=180):
        manifest["commands"].append({"argv": [str(a) for a in args],
                                     "cwd": str(cwd), "timeout_seconds": timeout,
                                     "log": log})
        _write_json(output / "manifest.json", manifest)
        with (output / log).open("wb") as stream:
            result = subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        manifest["commands"][-1]["returncode"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}); see {output / log}")

    try:
        build = output / "build"
        for name in source_hashes:
            target = build / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        target = build / "src/main/kotlin/poqi/qcast/ReferenceValidation.kt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DRIVER, target)
        execute([java, "-version"], "java-version.log", build, 30)
        execute([maven, "-version"], "maven-version.log", build, 30)
        classpath = build / "classpath.txt"
        command = [maven, "-B"] + (["-o"] if offline else []) + [
            "-f", build / "pom.xml", f"-Dmaven.repo.local={ROOT / 'results/qcast/m2'}",
            "compile", "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:build-classpath",
            f"-Dmdep.outputFile={classpath}",
        ]
        execute(command, "build.log", build)
        manifest["dependency_hashes"] = {str(Path(path)): sha256(path)
                                          for path in classpath.read_text().strip().split(os.pathsep)}
        execute([java, "-Djava.awt.headless=true", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-ea", "-cp",
                 str(build / "target/classes") + os.pathsep + classpath.read_text().strip(),
                 "poqi.qcast.ReferenceValidation", output / "reference.json"],
                "reference.log", build, 30)
        if "failed requirement" in (output / "reference.log").read_text(encoding="utf-8", errors="replace"):
            raise ValueError("authors' non-throwing require logged a failed requirement")
        for name, digest in source_hashes.items():
            if sha256(build / name) != digest:
                raise ValueError(f"author source changed in build: {name}")
        if verify_source(source) != source_hashes:
            raise ValueError("author checkout changed during validation")
        report = json.loads((output / "reference.json").read_text(encoding="utf-8"))
        audit = audit_report(report)
        _write_json(output / "audit.json", audit)
        manifest["status"] = "passed"
        manifest["artifact_hashes"] = {name: sha256(output / name) for name in
                                      ("reference.json", "reference.log", "audit.json", "build.log",
                                       "java-version.log", "maven-version.log")}
        return manifest
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest["utc_finished"] = datetime.now(timezone.utc).isoformat()
        _write_json(output / "manifest.json", manifest)


def audit_report(report):
    """Recompute small-case metrics, residual allocation and physical accounting.

    Exhaustive simple-path search is an oracle for these tiny fixtures only;
    it is neither a scalable implementation nor a claimed port of Q-CAST.
    """
    import networkx as nx

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(report["schema_version"] == 1 and report["source_commit"] == REVISION,
            "unexpected schema or source revision")
    require(report["D"] == 1 and report["status"] == "passed", "native checks did not pass")
    expected_counts = {
        "direct_unit": [1], "direct_memory_bottleneck": [2],
        "direct_channel_bottleneck": [1], "direct_partial_link_failure": [2],
        "direct_no_memory": [0], "chain_success": [1], "chain_pivot_memory_blocked": [0],
        "chain_link_failure": [0], "chain_swap_failure": [0], "chain_width_two": [2],
        "diamond_memory_detour": [1], "diamond_competing_requests": [1, 1],
        "widest_first_counterexample": [2], "recovery_disabled_failure": [0],
        "recovery_repairs_failed_segment": [1], "recovery_detour_failure": [0],
    }
    cases = report["controlled_cases"]
    require(len(cases) == len(expected_counts) and {c["name"] for c in cases} == set(expected_counts),
            "missing, duplicate or unexpected controlled cases")
    audited = []
    allocation_count = 0
    for case in cases:
        name = case["name"]
        lines = case["topology"].strip().splitlines()
        n, alpha, q, k = int(lines[0]), float(lines[1]), float(lines[2]), int(lines[3])
        nodes = [[float(v) for v in line.split()] for line in lines[4:4+n]]
        capacities = [int(row[0]) for row in nodes]
        demands = [tuple(sorted(pair)) for pair in case["requests"]]
        require(len(demands) == len(set(demands)) and all(s != d for s, d in demands),
                f"{name}: native requests must be unique unordered pairs")
        edges = [tuple(map(int, line.split())) for line in lines[4+n:]]
        channels = case["channels"]
        expected_edges = [sorted((u, v)) for u, v, count in edges for _ in range(count)]
        require([c["edge"] for c in channels] == expected_edges, f"{name}: channel topology mismatch")
        require([c["channel"] for c in channels] == list(range(len(channels))), f"{name}: channel identity")
        graph = nx.Graph()
        graph.add_nodes_from(range(n))
        graph.add_edges_from((u, v) for u, v, _ in edges)
        remaining = capacities.copy()
        available = {tuple(sorted((u, v))): count for u, v, count in edges}
        initial_available = available.copy()
        probabilities = {edge: math.exp(-alpha * math.dist(nodes[edge[0]][1:], nodes[edge[1]][1:]))
                         for edge in available}

        def edge_keys(path):
            return [tuple(sorted(edge)) for edge in zip(path, path[1:])]

        def candidate(s, d):
            candidates = []
            for path in nx.all_simple_paths(graph, s, d):
                keys = edge_keys(path)
                width = min(remaining[s], remaining[d],
                            min((remaining[v] // 2 for v in path[1:-1]), default=8),
                            min(available[e] for e in keys))
                if width > 0:
                    candidates.append((width, expected_yield([probabilities[e] for e in keys], width, q)))
            if not candidates:
                return None
            width = max(w for w, _ in candidates)
            return width, max(score for w, score in candidates if w == width)

        def consume(allocation, request_pairs):
            nonlocal allocation_count
            path, width, score = allocation["nodes"], allocation["width"], allocation["score"]
            require(len(path) >= 2 and len(path) == len(set(path)), f"{name}: invalid simple path")
            require((path[0], path[-1]) in [tuple(p) for p in request_pairs], f"{name}: wrong demand")
            keys = edge_keys(path)
            require(all(e in available for e in keys), f"{name}: nonexistent path edge")
            actual = candidate(path[0], path[-1])
            require(actual is not None and width == actual[0], f"{name}: wrong feasible width")
            oracle = expected_yield([probabilities[e] for e in keys], width, q)
            require(math.isclose(score, oracle, abs_tol=1e-12, rel_tol=1e-12), f"{name}: path metric")
            others = [candidate(*pair) for pair in request_pairs]
            best = max(c[1] for c in others if c is not None)
            require(score > 0 and math.isclose(score, best, abs_tol=1e-12, rel_tol=1e-12),
                    f"{name}: candidate selection disagrees with exhaustive oracle")
            for u, v in zip(path, path[1:]):
                remaining[u] -= width
                remaining[v] -= width
                available[tuple(sorted((u, v)))] -= width
            require(min(remaining) >= 0 and min(available.values()) >= 0, f"{name}: overallocated resources")
            allocation_count += 1

        for allocation in case["major_paths"]:
            consume(allocation, case["requests"])
        require(not any(c is not None and c[1] > 0 for c in
                        (candidate(*pair) for pair in case["requests"])), f"{name}: P2 stopped prematurely")
        for recovery in case["recovery_paths"]:
            allocation = recovery["path"]
            major = recovery["major"]
            require(case["recovery_enabled"] and major in [p["nodes"] for p in case["major_paths"]],
                    f"{name}: recovery has no major path")
            require(all(v in major for v in (allocation["nodes"][0], allocation["nodes"][-1]))
                    and 1 <= major.index(allocation["nodes"][-1])-major.index(allocation["nodes"][0]) <= k,
                    f"{name}: recovery endpoints outside k")
            consume(allocation, [[allocation["nodes"][0], allocation["nodes"][-1]]])
        assigned_counts = Counter(tuple(c["edge"]) for c in channels if c["assigned"])
        require(all(assigned_counts[e] == initial_available[e] - available[e] for e in available),
                f"{name}: exclusive channel accounting")
        occupied = [sum(c["assigned"] and v in c["edge"] for c in channels) for v in range(n)]
        require(occupied == case["occupied_qubits_after_P2"] == [c-r for c, r in zip(capacities, remaining)],
                f"{name}: memory accounting")
        require(case["remaining_qubits_after_P2"] == remaining, f"{name}: residual memory accounting")
        require(all(math.isclose(c["p"], probabilities[tuple(c["edge"])], abs_tol=1e-12) for c in channels),
                f"{name}: channel probability")
        require(all(not c["success"] or c["assigned"] for c in channels), f"{name}: unassigned link succeeded")
        attempts, successes = sum(c["assigned"] for c in channels), sum(c["success"] for c in channels)
        require(attempts == case["effective_channel_attempts"] and successes == case["successful_links"],
                f"{name}: generation accounting")
        post = case["post_p4_channels"]
        require([c["channel"] for c in post] == list(range(len(channels))), f"{name}: post-P4 channel IDs")
        swapped_ends = set()
        for channel, flags in zip(channels, post):
            for endpoint, flag in zip(channel["edge"], (flags["s1"], flags["s2"])):
                if flag:
                    require(channel["success"], f"{name}: swap used failed link")
                    swapped_ends.add((endpoint, channel["channel"]))
        per_node = Counter(node for node, _ in swapped_ends)
        require(all(count % 2 == 0 for count in per_node.values()), f"{name}: unpaired swap endpoint")
        internal = set()
        successful_ends = []
        for swap in case["successful_swap_inputs"]:
            pivot, inputs = swap["node"], swap["channels"]
            require(len(inputs) == 2 and inputs[0] != inputs[1], f"{name}: invalid swap pair")
            require(all((pivot, channel) in swapped_ends for channel in inputs), f"{name}: successful swap lacks input")
            successful_ends.extend((pivot, channel) for channel in inputs)
            internal.add((pivot, *sorted(inputs)))
        require(len(successful_ends) == len(set(successful_ends)), f"{name}: reused successful swap input")
        require(len(swapped_ends)//2 == case["swap_attempts"] and len(internal) == case["successful_swaps"],
                f"{name}: swap totals disagree with physical endpoints")
        counts = case["ebits_per_pair"]
        require(counts == expected_counts[name], f"{name}: unexpected delivery")
        require(counts == [len(paths) for paths in case["physical_delivery_channels"]],
                f"{name}: physical delivery count")
        used = []
        for demand, paths in zip(case["requests"], case["physical_delivery_channels"]):
            for path in paths:
                current = demand[0]
                visited = {current}
                previous_channel = None
                for channel_id in path:
                    require(isinstance(channel_id, int) and 0 <= channel_id < len(channels), f"{name}: bad channel ID")
                    channel = channels[channel_id]
                    require(channel["success"] and current in channel["edge"], f"{name}: broken delivery")
                    if previous_channel is None:
                        require((current, channel_id) not in swapped_ends, f"{name}: swapped source endpoint")
                    else:
                        require((current, *sorted((previous_channel, channel_id))) in internal,
                                f"{name}: delivery lacks internal connection")
                    u, v = channel["edge"]
                    current = v if current == u else u
                    require(current not in visited, f"{name}: cyclic delivery")
                    visited.add(current)
                    used.append(channel_id)
                    previous_channel = channel_id
                require(current == demand[1] and previous_channel is not None
                        and (current, previous_channel) not in swapped_ends, f"{name}: wrong delivery endpoint")
        require(len(used) == len(set(used)), f"{name}: physical channel reused across delivered ebits")
        total, served = sum(counts), sum(c > 0 for c in counts)
        require(total == case["delivered_ebits"] and served == case["served_sd_pairs"] == case["useful_unit_requests"]
                and total-served == case["surplus_ebits_for_one_request_per_pair"], f"{name}: outcome accounting")
        require(0 <= case["successful_swaps"] <= case["swap_attempts"] <= successes,
                f"{name}: swap accounting")
        require(case["successful_swaps"] >= len(used)-total, f"{name}: delivery lacks successful swaps")
        require(case["reset_clean"] is True, f"{name}: incomplete reset")
        audited.append({"name": name, "assigned_channels": attempts, "successful_links": successes,
                        "swap_attempts": case["swap_attempts"], "delivered_ebits": total,
                        "useful_unit_requests": served})
    require(len(report["metric_queries"]) == 2, "missing metric queries")
    for metric in report["metric_queries"]:
        require(math.isclose(metric["score"], expected_yield(metric["link_ps"], metric["width"],
                                                           metric["q"]), abs_tol=1e-12),
                "independent metric query mismatch")
    native = report["native_work"]
    require(native["deterministic_slots"] == [[1, 2], [1, 2]], "native deterministic work accounting")
    require(native["repeated_seed_identical"] and native["reset_clean_after_every_slot"], "native reset/replay")
    require(native["seeded_p_half_slots"] == [[1, 1], [1, 2], [1, 1], [0, 0], [1, 1], [1, 1], [1, 1], [1, 1]],
            "native seeded-work replay changed")
    duplicate = native["duplicate_pair_diagnostic"]
    require(duplicate["physical_ebits"] == 2 and duplicate["reported_ebits"] == 4
            and duplicate["reported_pair_entries_served"] == 2, "duplicate-pair accounting diagnostic")
    return {"status": "passed", "method": "independent exhaustive path/count oracle and physical-channel audit",
            "controlled_cases": len(audited), "path_allocations_checked": allocation_count,
            "metric_queries_checked": len(report["metric_queries"]), "cases": audited}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "results/qcast/QuantumRouting")
    parser.add_argument("--maven", type=Path,
                        default=ROOT / "results/qcast/tools/apache-maven-3.9.9/bin/mvn.cmd")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--online", action="store_true", help="allow Maven dependency downloads")
    args = parser.parse_args()
    result = run_reference(args.source, args.maven, args.output, offline=not args.online)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()

"""Drop-when-stuck recovery on cycles and grids, with outage and starvation metrics.

Network-scale runs of the root SeQUeNCe simulator before any crossover sweep.
Every arm of one seed sees the same demand pairs, the same generation times and
the same request times. Arms differ in the swap policy, the admission rule and
the recovery rule:

``none``            no recovery and no expiry
``drop<W>``         drop-when-stuck with patience W, no expiry
``cutoff<T>``       no drop rule, every pair expires T after its oldest ancestor

Demand is sparse, because lockups need pair types that nobody requests. Each
seed draws its demand pairs from the node pairs at distance two or more. Their
number is a fixed share of all node pairs. All demand pairs get one rate, set so
that shortest-path service would use the stated fraction of all generated pairs. Requests of each demand pair are served from
their own queue.

An interruption of a demand pair is an interval in which one of its requests
waits and none completes. An outage is an interruption at least as long as
``--outage``. Both are measured on the window after the warm-up.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
from importlib.metadata import version
from itertools import combinations
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess

import networkx as nx
from scipy.stats import t as student_t

from poqi.simulation import run_simulation

NETWORKS = {
    "cycle8": lambda: nx.cycle_graph(8),
    "cycle12": lambda: nx.cycle_graph(12),
    "grid3x3": lambda: nx.convert_node_labels_to_integers(nx.grid_2d_graph(3, 3)),
    "grid4x4": lambda: nx.convert_node_labels_to_integers(nx.grid_2d_graph(4, 4)),
    "grid5x5": lambda: nx.convert_node_labels_to_integers(nx.grid_2d_graph(5, 5)),
}
METRICS = ("satisfaction", "minimum_satisfaction", "starved_fraction", "jain_fairness",
           "outage_fraction", "longest_interruption", "any_pair_longest_interruption",
           "zero_service", "mean_latency", "final_backlog", "drops_per_completion",
           "expired_per_completion", "swaps_per_completion", "rejected_fraction")


def network(name):
    graph = NETWORKS[name]()
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return graph


def demand_set(graph, seed, share, load):
    """Seeded demand pairs at distance two or more, and their common rate."""
    distance = dict(nx.all_pairs_shortest_path_length(graph))
    far = [pair for pair in combinations(graph.nodes, 2) if distance[pair[0]][pair[1]] >= 2]
    count = max(2, round(share * len(graph) * (len(graph) - 1) / 2))
    pairs = sorted(random.Random(7919 * seed + 13).sample(far, count))
    hops = {pair: distance[pair[0]][pair[1]] for pair in pairs}
    rate = load * graph.number_of_edges() / sum(hops.values())
    return {pair: rate for pair in pairs}, hops


def parse_arm(label):
    """``none``, ``drop5`` or ``cutoff30`` as simulator keyword arguments."""
    if label == "none":
        return {}
    for prefix, build in (("drop", lambda v: {"recovery_policy": "drop_when_stuck", "stuck_patience": v}),
                          ("cutoff", lambda v: {"cutoff_time": v})):
        if label.startswith(prefix):
            return build(float(label[len(prefix):]))
    raise ValueError(f"unknown recovery arm: {label}")


def observe(result, hops):
    """One row of run-level measurements from a simulator result."""
    continuity = result["service_continuity"]
    rows = continuity["by_pair"]
    window = continuity["window"][1] - continuity["window"][0]
    completed = sum(row["completed_requests"] for row in rows)
    offered_rate = sum(row["demand_rate"] for row in rows)
    ops = continuity["operations"]
    waits = [row["completed_latency_sum"] / row["completed_requests"] for row in rows
             if row["completed_requests"]]
    by_hops = {}
    for row in rows:
        by_hops.setdefault(hops[tuple(row["endpoints"])], []).append(row["satisfaction"])
    per = (lambda count: count / completed if completed else None)
    return {
        "satisfaction": completed / (window * offered_rate),
        "minimum_satisfaction": continuity["minimum_satisfaction"],
        "starved_fraction": continuity["starved_pairs"] / len(rows),
        "jain_fairness": continuity["jain_fairness"],
        # Share of the window, averaged over demand pairs, spent in outages of that pair.
        "outage_fraction": statistics.fmean(row["outage_fraction"] for row in rows),
        "longest_interruption": max(row["longest_interruption"] for row in rows),
        "any_pair_longest_interruption": continuity["all_pairs"]["longest_interruption"],
        "zero_service": int(completed == 0),
        "offered_requests": sum(row["offered_requests"] for row in rows),
        "completed_requests": completed,
        **ops,
        "by_pair": rows,
        "mean_latency": per(sum(row["completed_latency_sum"] for row in rows)),
        "worst_pair_mean_latency": max(waits, default=None),
        "final_backlog": result["unserved_requests"],
        "drops_per_completion": per(ops["stuck_drops"]),
        "expired_per_completion": per(ops["expired_pairs"]),
        "swaps_per_completion": per(ops["swaps"]),
        "rejected_fraction": ops["admission_rejections"] / ops["offered_generation"] if ops["offered_generation"] else None,
        "satisfaction_by_hops": {str(h): statistics.fmean(values) for h, values in sorted(by_hops.items())},
    }


def run(task):
    name, memory, policy, admission, arm, seed, options = task
    graph = network(name)
    demand, hops = demand_set(graph, seed, options["share"], options["load"])
    result = run_simulation(graph, demand, memory_slots=memory, swap_policy=policy,
                            admission_policy=admission, service_order="per_pair",
                            horizon=options["horizon"], measure_from=options["warmup"],
                            outage_threshold=options["outage"], seed=seed, record_events=False,
                            ticks_per_time_unit=1_000_000, **parse_arm(arm))
    if result["pair_conservation_residual"] != 0:
        raise AssertionError("pair conservation failed")
    return {"network": name, "memory": memory, "policy": policy, "admission": admission, "arm": arm,
            "seed": seed, "demand_pairs": len(demand), "demand_rate": next(iter(demand.values())),
            **observe(result.to_dict(), hops)}


def interval(values):
    """Mean and pointwise 95% Student-t interval across seeds."""
    values = [value for value in values if value is not None]
    if not values:
        return [None, None, None]
    mean = statistics.fmean(values)
    if len(values) < 2:
        return [mean, None, None]
    half = student_t.ppf(0.975, len(values) - 1) * statistics.stdev(values) / len(values) ** 0.5
    return [mean, mean - half, mean + half]


def summarise(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["network"], row["memory"], row["policy"], row["admission"], row["arm"]), []).append(row)
    return [{"network": key[0], "memory": key[1], "policy": key[2], "admission": key[3], "arm": key[4],
             "seeds": len(group), "zero_service_runs": sum(row["zero_service"] for row in group),
             **{metric: interval([row[metric] for row in group]) for metric in METRICS}}
            for key, group in groups.items()]


def save_records(path, data, compress):
    if compress:
        encoded = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
        path = path.with_suffix(".json.gz")
        path.write_bytes(gzip.compress(encoded, compresslevel=6, mtime=0))
    else:
        path.write_text(json.dumps(data, indent=1, allow_nan=False), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--networks", nargs="+", default=["cycle8", "cycle12", "grid3x3", "grid4x4"],
                        choices=sorted(NETWORKS))
    parser.add_argument("--memory", type=int, nargs="+", default=[2, 3, 4, 6, 8])
    parser.add_argument("--policies", nargs="+", default=["pressure_relaxed", "pressure_oriented"])
    parser.add_argument("--admissions", nargs="+", default=["reserved"], choices=["reserved", "tail_drop"])
    parser.add_argument("--arms", nargs="+",
                        default=["none", "drop0", "drop2", "drop5", "drop10", "drop30", "cutoff10", "cutoff30"])
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(11301, 11307)))
    parser.add_argument("--share", type=float, default=0.12, help="share of node pairs that carry demand")
    parser.add_argument("--load", type=float, default=0.1,
                        help="fraction of generated pairs that shortest-path service would use")
    parser.add_argument("--horizon", type=float, default=2000)
    parser.add_argument("--warmup", type=float, default=500)
    parser.add_argument("--outage", type=float, default=50, help="interruption length that counts as an outage")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--gzip", action="store_true", help="save compact compressed seed records and summaries")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output directory must be new")
    for arm in args.arms:
        parse_arm(arm)
    options = {"share": args.share, "load": args.load, "horizon": args.horizon,
               "warmup": args.warmup, "outage": args.outage}
    tasks = [(name, memory, policy, admission, arm, seed, options)
             for name in args.networks for memory in args.memory for policy in args.policies
             for admission in args.admissions for arm in args.arms for seed in args.seeds]
    root = Path(__file__).resolve().parents[1]
    git = lambda *words: subprocess.run(["git", *words], capture_output=True, text=True, cwd=root).stdout.strip()
    commit, uncommitted = git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))
    sources = ["scripts/recovery_baseline.py", "src/poqi/simulation/sequence_adapter.py",
               "src/poqi/simulation/inventory.py"]
    source_hashes = {name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                     for name in sources}
    sequence_commit = git("-C", "SeQUeNCe", "rev-parse", "HEAD")
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run, tasks, chunksize=1))
    summary = summarise(rows)
    demand = {name: {str(seed): [list(pair) for pair in demand_set(network(name), seed, args.share, args.load)[0]]
                     for seed in args.seeds} for name in args.networks}
    args.output.mkdir(parents=True)
    files = [save_records(args.output / "runs.json", rows, args.gzip),
             save_records(args.output / "summary.json", summary, args.gzip)]
    manifest = {"commit": commit, "uncommitted_changes": uncommitted, "runs": len(rows), "demand_pairs": demand,
                "source_sha256_lf": source_hashes, "sequence_commit": sequence_commit,
                "python": platform.python_version(), "versions": {name: version(name) for name in ("numpy", "networkx", "scipy")},
                "window_convention": "[warmup, horizon) for events and costs; final_backlog is the stock at horizon",
                "file_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
                **{key: value for key, value in vars(args).items() if key not in ("output", "workers")}}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({"runs": len(rows), "groups": len(summary), "output": str(args.output)}))


if __name__ == "__main__":
    main()

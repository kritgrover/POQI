"""Saturated service of longer chains in the root simulator.

Unit-rate Poisson generation on every link of a path, one end-to-end demand
class with a request always waiting, uniform budgets, no expiry. Compares the
original pressure policy, the orientation-guarded one and corrected balancing
on identical generation times.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random
import statistics

import networkx as nx

from poqi.simulation import run_simulation

POLICIES = ("pressure_oriented", "pressure_relaxed", "balancing")
TICKS = 1_000_000


def run(task):
    nodes, memory, policy, seed, horizon, warmup = task
    graph = nx.path_graph(nodes)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    events = []
    for index, edge in enumerate(graph.edges):
        rng = random.Random((seed + 1) * 1000003 + index)
        moment = rng.expovariate(1.0)
        while moment < horizon:
            tick = round(moment * TICKS)
            if tick < horizon * TICKS:
                events.append({"kind": "generate", "endpoints": edge, "time": tick / TICKS})
            moment += rng.expovariate(1.0)
    # More requests than generations on any link keeps the backlog permanent.
    events.append({"kind": "request", "endpoints": (0, nodes - 1), "time": 0, "count": len(events)})
    result = run_simulation(graph, {(0, nodes - 1): 1.0}, memory_slots=memory, swap_policy=policy,
                            horizon=horizon, trace=events, ticks_per_time_unit=TICKS)
    if result["unserved_requests"] == 0 or result["pair_conservation_residual"] != 0:
        raise AssertionError("backlog emptied or conservation failed")
    completed = sum(1 for event in result["events"] if event["kind"] == "complete" and event["time"] >= warmup)
    return {"links": nodes - 1, "memory": memory, "policy": policy, "seed": seed,
            "rate": completed / (horizon - warmup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--links", type=int, nargs="+", default=[2, 3, 4, 5])
    parser.add_argument("--memory", type=int, nargs="+", default=[2, 3, 4, 6, 8, 12])
    parser.add_argument("--seeds", type=int, nargs="+", default=[31, 32, 33, 34])
    parser.add_argument("--horizon", type=float, default=3000)
    parser.add_argument("--warmup", type=float, default=500)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output file must be new")
    tasks = [(links + 1, memory, policy, seed, args.horizon, args.warmup)
             for links in args.links for memory in args.memory for policy in POLICIES for seed in args.seeds]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run, tasks, chunksize=1))
    summary = [{"links": links, "memory": memory, "policy": policy,
                "mean_rate": statistics.fmean(r["rate"] for r in rows
                                              if (r["links"], r["memory"], r["policy"]) == (links, memory, policy))}
               for links in args.links for memory in args.memory for policy in POLICIES]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"runs": rows, "summary": summary}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

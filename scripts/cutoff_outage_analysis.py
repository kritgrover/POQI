"""Outage length and request delay on the two-slot chain when storage has a cutoff.

With a finite cutoff the wrong-origin pair of the two-slot lockup expires, so the
trap is temporary. This script measures how long service is impossible and what
that does to the request queue, for the original and the orientation-guarded
pressure policy on identical arrivals. Runs use the root SeQUeNCe simulator.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import statistics

import networkx as nx
from scipy.stats import t as student_t

from poqi.simulation import run_simulation

END = (0, 2)
POLICIES = ("pressure_relaxed", "pressure_oriented")


def horizon_for(cutoff, demand, cycles):
    """Long enough for about ``cycles`` outage-and-recovery cycles at this load."""
    saturated = 2 / 3
    return float(max(4000, round(cycles * (20 + cutoff * saturated / (saturated - demand)))))


def observe(result, warmup):
    """Window measurements from one event log. Times are in abstract units."""
    horizon = result["horizon"]
    cutoff = result["cutoff_time"]
    queue = 0
    last = warmup
    area = 0.0
    completed = offered = served_in_outage = 0
    latency_sum = 0.0
    wrong = {}          # live wrong-origin pair id -> (creation time, deadline time)
    outages = []        # (start, end, age of oldest ancestor at start, ended by expiry)
    for event in result["events"]:
        time = event["time"]
        if time >= warmup:
            area += queue * (time - last)
            last = time
        kind = event["kind"]
        removed = event.get("removed", [])
        for identifier in removed:
            if identifier in wrong:
                start, deadline = wrong.pop(identifier)
                outages.append((start, time, start - (deadline - cutoff) if cutoff else None,
                                kind == "expire"))
        if kind == "swap" and event["pivot"] != 1:
            # Only an endpoint can make a pair whose center qubit sits in the
            # other link's reservation. Service is impossible until it leaves.
            record = event["created"][0]
            deadline = record["deadline_tick"]
            wrong[record["id"]] = (time, None if deadline is None else deadline / result["ticks_per_time_unit"])
        if time >= warmup:
            if kind == "complete":
                completed += 1
                latency_sum += event["latency"]
                served_in_outage += bool(wrong)
            elif kind == "request":
                offered += 1
        queue = event["queue_length"]
    area += queue * (horizon - last)
    for start, _ in wrong.values():
        outages.append((start, horizon, None, False))
    window = horizon - warmup
    inside = [(max(a, warmup), min(b, horizon)) for a, b, _, _ in outages if b > warmup]
    finished = [(b - a, age) for a, b, age, expired in outages if expired and a >= warmup]
    return {
        "throughput": completed / window,
        "offered": offered / window,
        "mean_queue": area / window,
        "mean_latency": latency_sum / completed if completed else None,
        "final_queue": result["unserved_requests"],
        "outage_fraction": sum(b - a for a, b in inside) / window,
        "completions_during_outage": served_in_outage,
        "outages": len(finished),
        "mean_outage": statistics.fmean(d for d, _ in finished) if finished else None,
        "mean_square_outage": statistics.fmean(d * d for d, _ in finished) if finished else None,
        "mean_age_at_start": statistics.fmean(age for _, age in finished) if finished else None,
        "outage_plus_age_minus_cutoff": (max(abs(d + age - cutoff) for d, age in finished)
                                         if finished and cutoff else None),
    }


def run(task):
    policy, cutoff, demand, seed, horizon, warmup = task
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    result = run_simulation(graph, {END: demand}, memory_slots=2, cutoff_time=cutoff,
                            swap_policy=policy, horizon=horizon, seed=seed,
                            ticks_per_time_unit=1_000_000)
    if result["pair_conservation_residual"] != 0:
        raise AssertionError("pair conservation failed")
    return {"policy": policy, "cutoff": cutoff, "demand": demand, "seed": seed,
            "horizon": horizon, "warmup": warmup, **observe(result.to_dict(), warmup)}


def interval(values):
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return [values[0] if values else None, None, None]
    mean = statistics.fmean(values)
    half = student_t.ppf(0.975, len(values) - 1) * statistics.stdev(values) / len(values) ** 0.5
    return [mean, mean - half, mean + half]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoffs", type=float, nargs="+", default=[3, 10, 30, 100, 300])
    parser.add_argument("--demands", type=float, nargs="+", default=[0.25, 0.5])
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(11271, 11279)))
    parser.add_argument("--cycles", type=float, default=30)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output directory must be new")
    tasks = []
    for cutoff in args.cutoffs:
        for demand in args.demands:
            horizon = horizon_for(cutoff, demand, args.cycles)
            warmup = float(max(200, round(5 * cutoff)))
            tasks += [(policy, cutoff, demand, seed, horizon, warmup)
                      for policy in POLICIES for seed in args.seeds]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(run, tasks, chunksize=1))
    summary = []
    keys = ("throughput", "mean_queue", "mean_latency", "outage_fraction", "mean_outage",
            "mean_square_outage", "mean_age_at_start")
    for cutoff in args.cutoffs:
        for demand in args.demands:
            for policy in POLICIES:
                group = [r for r in rows if (r["policy"], r["cutoff"], r["demand"]) == (policy, cutoff, demand)]
                identity = [r["outage_plus_age_minus_cutoff"] for r in group
                            if r["outage_plus_age_minus_cutoff"] is not None]
                summary.append({"policy": policy, "cutoff": cutoff, "demand": demand,
                                "horizon": group[0]["horizon"], "warmup": group[0]["warmup"],
                                "seeds": len(group), "outages": sum(r["outages"] for r in group),
                                "largest_identity_residual": max(identity) if identity else None,
                                "completions_during_outage": sum(r["completions_during_outage"] for r in group),
                                **{key: interval([r[key] for r in group]) for key in keys}})
    args.output.mkdir(parents=True)
    (args.output / "runs.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

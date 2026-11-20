"""Matched-seed evaluation of the one-count memory-pressure swap relaxation."""

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

import networkx as nx

from poqi.analysis.blocking import observe_blocking
from poqi.reporting import create_output, provenance, write_json
from poqi.simulation import run_simulation

try:
    from .verify_implementation_results import interval, require
except ImportError:
    from verify_implementation_results import interval, require


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("chain_lossless", "chain_cutoff10", "star_cutoff10")
POLICIES = ("balancing", "pressure_relaxed", "physical")
METRICS = ("throughput", "blocking_probability", "mean_backlog", "final_backlog",
           "backlog_growth_rate", "minimum_pair_satisfaction", "swaps_per_completion",
           "swaps", "pressure_relaxed_swaps")


def specification(name):
    require(name in SCENARIOS, "unknown policy scenario")
    star = name == "star_cutoff10"
    graph = nx.star_graph(3) if star else nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    demand = {(1, 2): .6, (1, 3): .3, (2, 3): .1} if star else {(0, 2): 1.0}
    return graph, demand, None if name == "chain_lossless" else 10.0, [3, 4, 6, 8, 16, None] if star else [2, 3, 4, 8, 16, None]


def observe_policy(data, *, warmup=0.0):
    """Replay accounting, policy predicates and FIFO; integrate all queued requests."""
    base = observe_blocking(data, warmup=warmup)
    if data["swap_policy"] == "pressure_relaxed":
        require(type(data.get("pressure_relaxed_swaps")) is int and data["pressure_relaxed_swaps"] >= 0,
                "missing or invalid relaxed-action counter")
    ticks, horizon = data["ticks_per_time_unit"], data["horizon"]
    start, end = round(warmup * ticks), round(horizon * ticks)
    duration = horizon - warmup
    limits = {r["node"]: r["memory_slots"] for r in data["occupancy_by_node"]}
    quotas = {(r["node"], q["neighbor"]): q["slots"] for r in data["reservations"] for q in r["neighbors"]}
    pair = lambda ends: frozenset(ends)
    counts, occupancy, origins = Counter(), Counter(), Counter()
    live, pending, seen_requests = {}, {}, set()
    offered, completed = Counter(), Counter()
    window_swaps = window_relaxed = total_relaxed = 0
    previous = area = 0
    initial_backlog = None
    for event in data["events"]:
        tick, kind = event["tick"], event["kind"]
        area += len(pending) * max(0, min(tick, end) - max(previous, start)) / ticks
        if initial_backlog is None and tick >= start:
            initial_backlog = len(pending)
        within = start <= tick < end
        if kind == "swap":
            pivot = event["pivot"]
            x, y = event["created"][0]["endpoints"]
            left, right, output = counts[pair((pivot, x))], counts[pair((pivot, y))], counts[pair((x, y))]
            preferred = output + 1 <= min(left - 1, right - 1)
            pressure = limits[pivot] is not None and occupancy[pivot] >= limits[pivot]
            for identifier in event["removed"]:
                origin = next(r["neighbor"] for r in live[identifier]["origins"] if r["node"] == pivot)
                quota = quotas.get((pivot, origin)) if data["admission_policy"] == "reserved" else None
                pressure |= quota is not None and quota > 0 and origins[pivot, origin] >= quota
            flag = event.get("pressure_relaxed", False)
            require(type(flag) is bool, "invalid relaxed-action flag")
            if data["swap_policy"] == "balancing":
                require(preferred and not flag, "balancing swap violates preference")
            elif data["swap_policy"] == "pressure_relaxed":
                require(preferred or (pressure and output <= min(left - 1, right - 1)), "pressure swap violates rule")
                require(flag == (not preferred), "incorrect relaxed-action flag")
            else:
                require(not flag, "relaxation flag on another policy")
            total_relaxed += flag
            if within:
                window_swaps += 1
                window_relaxed += flag
        for identifier in event.get("removed", []):
            item = live.pop(identifier)
            counts[pair(item["endpoints"])] -= 1
            for origin in item["origins"]:
                occupancy[origin["node"]] -= 1
                origins[origin["node"], origin["neighbor"]] -= 1
        for item in event.get("created", []):
            live[item["id"]] = item
            counts[pair(item["endpoints"])] += 1
            for origin in item["origins"]:
                occupancy[origin["node"]] += 1
                origins[origin["node"], origin["neighbor"]] += 1
        if kind == "request":
            require(event["request_id"] not in seen_requests, "duplicate queued request")
            seen_requests.add(event["request_id"])
            pending[event["request_id"]] = (tuple(event["endpoints"]), tick)
            if within:
                offered[pair(event["endpoints"])] += 1
        elif kind == "complete":
            require(pending and next(iter(pending)) == event["request_id"], "FIFO completion mismatch")
            endpoints, arrived = pending.pop(event["request_id"])
            require(pair(endpoints) == pair(event["endpoints"])
                    and math.isclose(event["latency"], (tick - arrived) / ticks, abs_tol=1e-9), "request/latency mismatch")
            if within:
                completed[pair(endpoints)] += 1
        require(event["queue_length"] == len(pending), "logged backlog mismatch")
        previous = tick
    require(total_relaxed == data.get("pressure_relaxed_swaps", 0), "relaxed counter mismatch")
    require([(r["id"], tuple(r["endpoints"]), r["arrival_tick"]) for r in data["unserved_queue"]]
            == [(identifier, endpoints, tick) for identifier, (endpoints, tick) in pending.items()], "final backlog mismatch")
    require(len(pending) == data["unserved_requests"], "unserved count mismatch")
    backlog = Counter(pair(endpoints) for endpoints, _ in pending.values())
    rows = []
    for row in data["service_by_pair"]:
        key = pair(row["endpoints"])
        rows.append({"endpoints": row["endpoints"], "demand_rate": row["demand_rate"],
                     "offered_requests": offered[key], "completed_requests": completed[key],
                     "throughput": completed[key] / duration, "final_backlog": backlog[key]})
    require(sum(completed.values()) == base["completed_requests"], "window completions mismatch")
    return {"throughput": base["throughput"], "blocking_probability": base["blocking_probability"],
            "offered_generation": base["offered"], "admitted_generation": base["accepted"],
            "completed_requests": base["completed_requests"], "swaps": window_swaps,
            "pressure_relaxed_swaps": window_relaxed,
            "swaps_per_completion": window_swaps / base["completed_requests"] if base["completed_requests"] else None,
            "mean_backlog": area / duration, "final_backlog": len(pending),
            "backlog_growth_rate": (len(pending) - initial_backlog) / duration,
            "minimum_pair_satisfaction": min((r["throughput"] / r["demand_rate"] for r in rows if r["demand_rate"] > 0), default=None),
            "input_signature": base["exogenous_signature"],
            "event_signature": hashlib.sha256(json.dumps(data["events"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "per_pair": rows, "rejections_by_reason": base["rejections_by_reason"]}


def summarize_group(records):
    require(bool(records), "empty policy group")
    return {"n": len(records), "zero_completion_runs": sum(r["completed_requests"] == 0 for r in records),
            "undefined_swap_ratios": sum(r["swaps_per_completion"] is None for r in records),
            **{metric: interval([r[metric] for r in records]) for metric in METRICS}}


def paired_difference(left, right, metric):
    """Left minus right, matched by seed; never pair by file ordering."""
    left_by_seed, right_by_seed = ({r["seed"]: r[metric] for r in records} for records in (left, right))
    require(len(left_by_seed) == len(left) and len(right_by_seed) == len(right), "duplicate paired seed")
    require(bool(left_by_seed) and set(left_by_seed) == set(right_by_seed), "unmatched paired seeds")
    return interval([None if left_by_seed[seed] is None or right_by_seed[seed] is None else
                     left_by_seed[seed] - right_by_seed[seed] for seed in sorted(left_by_seed)])


def run_suite(output, *, horizon=2000, warmup=500, replicates=10, seed=4271):
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (horizon, warmup))
            and horizon > 10 and 0 <= warmup < horizon, "invalid observation window")
    require(type(replicates) is int and replicates >= 2 and type(seed) is int and seed >= 0, "invalid repetitions/seed")
    output = create_output(output)
    (output / "runs").mkdir()
    paths = (Path(__file__).resolve(), ROOT / "src/poqi/simulation/sequence_adapter.py",
             ROOT / "src/poqi/simulation/inventory.py", ROOT / "src/poqi/analysis/blocking.py")
    manifest = {**provenance(), "status": "running", "horizon": horizon, "warmup": warmup,
                "seeds": list(range(seed, seed + replicates)), "policies": list(POLICIES),
                "scenarios": {s: {"capacities": specification(s)[3]} for s in SCENARIOS}, "runs": [],
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                "protocol": "D=1, empty inventory, reserved admission, fixed horizons; fresh seeds matched across all policies/capacities; FIFO and all other dynamics unchanged",
                "pressure_rule": "One-count preference relaxation only at a full pivot or a consumed saturated positive origin quota",
                "intervals": "Pointwise 95% Student-t across independent seeds; differences paired by seed"}
    write_json(output / "manifest.json", manifest)
    try:
        for scenario in SCENARIOS:
            graph, demand, cutoff, capacities = specification(scenario)
            for capacity in capacities:
                for run_seed in manifest["seeds"]:
                    for policy in POLICIES:
                        label = "unlimited" if capacity is None else str(capacity)
                        identifier = f"{scenario}-c{label}-s{run_seed}-{policy}"
                        print(identifier, flush=True)
                        started = perf_counter()
                        data = run_simulation(graph, demand, memory_slots=capacity, cutoff_time=cutoff,
                                              distillation_pairs=1, horizon=horizon, seed=run_seed,
                                              ticks_per_time_unit=1000000, admission_policy="reserved",
                                              swap_policy=policy, record_events=True).to_dict()
                        observed = observe_policy(data, warmup=warmup)
                        case = {"id": identifier, "scenario": scenario, "capacity": capacity, "policy": policy,
                                "seed": run_seed, "horizon": horizon, "warmup": warmup,
                                "wall_seconds": perf_counter() - started, "artifact": f"runs/{identifier}.json.gz"}
                        with gzip.open(output / case["artifact"], "wt", encoding="utf-8") as stream:
                            json.dump({"case": case, "simulation": data, "observed": observed}, stream, allow_nan=False)
                        manifest["runs"].append(case)
                        write_json(output / "manifest.json", manifest)
        manifest["status"] = "completed"
        write_json(output / "manifest.json", manifest)
    except Exception as error:
        manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(output / "manifest.json", manifest)
        raise
    return output


def build_report(source):
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "completed", "experiment is incomplete")
    seeds = manifest["seeds"]
    require(len(seeds) >= 2 and len(seeds) == len(set(seeds)) and all(type(s) is int and s >= 0 for s in seeds), "invalid or duplicate seeds")
    require(manifest["policies"] == list(POLICIES) and set(manifest["scenarios"]) == set(SCENARIOS), "protocol coverage mismatch")
    require(all(manifest["scenarios"][s]["capacities"] == specification(s)[3] for s in SCENARIOS), "capacity protocol mismatch")
    expected = {(s, c, seed, policy) for s in SCENARIOS for c in specification(s)[3] for seed in seeds for policy in POLICIES}
    cases, signatures = {}, {}
    for case in manifest["runs"]:
        key = (case["scenario"], case["capacity"], case["seed"], case["policy"])
        require(key in expected and key not in cases, "unexpected or duplicate case")
        with gzip.open(source / case["artifact"], "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
        require(saved["case"] == case, "manifest/case mismatch")
        graph, demand, cutoff, _ = specification(case["scenario"])
        data = saved["simulation"]
        require(case["horizon"] == manifest["horizon"] == data["horizon"]
                and case["warmup"] == manifest["warmup"] and data["seed"] == case["seed"], "window/seed mismatch")
        require(data["distillation_pairs"] == 1 and data["initial_pairs"] == 0 and data["cutoff_time"] == cutoff
                and data["swap_policy"] == case["policy"] and data["admission_policy"] == "reserved"
                and data["ticks_per_time_unit"] == 1000000 and data["time_unit"] == "abstract", "simulation protocol mismatch")
        require({r["node"] for r in data["occupancy_by_node"]} == set(graph)
                and all(r["memory_slots"] == case["capacity"] for r in data["occupancy_by_node"]), "node/capacity mismatch")
        require({tuple(r["endpoints"]): r["demand_rate"] for r in data["service_by_pair"]} == demand, "demand mismatch")
        obs = observe_policy(data, warmup=case["warmup"])
        require(obs == saved["observed"], "saved metrics differ from event replay")
        match = (case["scenario"], case["seed"])
        require(match not in signatures or signatures[match] == obs["input_signature"], "unmatched exogenous inputs")
        signatures[match] = obs["input_signature"]
        cases[key] = {**case, **obs}
    require(set(cases) == expected, "missing experiment cases")
    report = {"source": str(source), "protocol": manifest["protocol"], "pressure_rule": manifest["pressure_rule"],
              "horizon": manifest["horizon"], "warmup": manifest["warmup"], "seeds": seeds,
              "intervals": manifest["intervals"], "validated_runs": len(cases), "unlimited_equivalent_pairs": 0,
              "summary": [], "paired": [], "per_pair": [], "observations": list(cases.values())}
    for scenario in SCENARIOS:
        for seed in seeds:
            left, right = cases[scenario, None, seed, "pressure_relaxed"], cases[scenario, None, seed, "balancing"]
            require(left["event_signature"] == right["event_signature"]
                    and all(left[m] == right[m] for m in METRICS), "unlimited pressure/balancing equivalence failed")
            report["unlimited_equivalent_pairs"] += 1
        for capacity in specification(scenario)[3]:
            groups = {p: [cases[scenario, capacity, seed, p] for seed in seeds] for p in POLICIES}
            for policy, rows in groups.items():
                identity = {"scenario": scenario, "capacity": capacity, "policy": policy}
                report["summary"].append({**identity, **summarize_group(rows)})
                for endpoints in specification(scenario)[1]:
                    selected = [next(r for r in row["per_pair"] if tuple(r["endpoints"]) == endpoints) for row in rows]
                    report["per_pair"].append({**identity, "endpoints": list(endpoints), "n": len(rows),
                                               "demand_rate": selected[0]["demand_rate"],
                                               **{m: interval([r[m] for r in selected]) for m in ("throughput", "final_backlog")}})
            for policy in ("pressure_relaxed", "physical"):
                report["paired"].append({"scenario": scenario, "capacity": capacity, "policy": policy,
                                         "reference": "balancing", "n": len(seeds),
                                         **{m: paired_difference(groups[policy], groups["balancing"], m) for m in METRICS}})
    return report


def write_report(report, output):
    output = create_output(output)
    write_json(output / "policy.json", report)
    for name in ("observations", "summary", "paired", "per_pair"):
        rows = report[name]
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(3, 3, figsize=(14, 10), constrained_layout=True)
    labels = {"balancing": "Corrected balancing", "pressure_relaxed": "Pressure relaxation", "physical": "Physical-swap diagnostic"}
    for index, scenario in enumerate(SCENARIOS):
        capacities = specification(scenario)[3]
        for offset, policy in enumerate(POLICIES):
            rows = [next(r for r in report["summary"] if r["scenario"] == scenario and r["policy"] == policy
                         and r["capacity"] == c) for c in capacities]
            x = [i + (offset - 1) * .06 for i in range(len(capacities))]
            for column, (metric, title) in enumerate((("throughput", "Completed requests / time unit"),
                                                      ("blocking_probability", "Rejected generation fraction"),
                                                      ("mean_backlog", "Time-average request backlog"))):
                y = [r[metric]["mean"] for r in rows]
                errors = [[r[metric]["mean"] - r[metric]["ci95"][0] for r in rows],
                          [r[metric]["ci95"][1] - r[metric]["mean"] for r in rows]]
                ax = axes[index, column]
                ax.errorbar(x, y, yerr=errors, fmt="o-", capsize=3, label=labels[policy])
                ax.set(xlabel="Slots per node", ylabel=title, title=scenario.replace("_", " "),
                       xticks=range(len(capacities)), xticklabels=["unlimited" if c is None else str(c) for c in capacities])
                ax.grid(alpha=.2)
                if column == 2:
                    ax.set_yscale("symlog", linthresh=1)
        axes[index, 0].legend(fontsize=7)
    fig.suptitle("Memory-aware swap pilot: matched seeds, mean and 95% t confidence intervals")
    fig.savefig(output / "policy.png", dpi=170)
    plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-runs", type=Path)
    parser.add_argument("--horizon", type=float, default=2000)
    parser.add_argument("--warmup", type=float, default=500)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--seed", type=int, default=4271)
    args = parser.parse_args()
    if args.from_runs:
        output = write_report(build_report(args.from_runs), args.output)
    else:
        source = run_suite(args.output, horizon=args.horizon, warmup=args.warmup, replicates=args.replicates, seed=args.seed)
        output = write_report(build_report(source), source / "report")
    print(f"Validated all policy runs and wrote {output}")


if __name__ == "__main__":
    main()

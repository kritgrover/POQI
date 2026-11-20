"""Frozen-policy demand/horizon study; paired windows are not extra repetitions."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gzip
import hashlib
from itertools import product
import json
import math
from pathlib import Path
from time import perf_counter

import networkx as nx

from poqi.reporting import create_output, provenance, write_json
from poqi.simulation import run_simulation

try:
    from .memory_policy_analysis import paired_difference
    from .robustness_observations import observe_robustness
    from .verify_implementation_results import interval, require
except ImportError:
    from memory_policy_analysis import paired_difference
    from robustness_observations import observe_robustness
    from verify_implementation_results import interval, require


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("chain_lossless", "chain_cutoff10")
DEMANDS = (.5, .75, 1.0)
CAPACITIES = (2, 3, 4, 8, None)
POLICIES = ("balancing", "pressure_relaxed")
WINDOWS = ("early", "late")
MEMORY_COMPARISONS = ((3, 4), (4, 8))
METRICS = ("throughput", "blocking_probability", "mean_backlog", "initial_backlog",
           "final_backlog", "backlog_growth_rate", "swaps_per_completion", "swaps",
           "pressure_relaxed_swaps")
HORIZON_METRICS = ("throughput", "blocking_probability", "mean_backlog", "final_backlog",
                   "backlog_growth_rate", "swaps_per_completion")
FLAGS = ("zero_service", "zero_service_with_demand", "single_partner_absorbing_stall")


def validate_parameters(horizon, warmup, split, replicates, seed, workers):
    require(all(type(x) in (int, float) and math.isfinite(x) for x in (horizon, warmup, split))
            and horizon > 10 and 0 <= warmup < split < horizon, "invalid observation windows")
    require(type(replicates) is int and replicates >= 2 and type(seed) is int and seed >= 0,
            "invalid repetitions/seed")
    require(type(workers) is int and workers >= 1, "invalid worker count")


def _tasks(function, arguments, workers):
    if workers == 1:
        for args in arguments:
            yield function(args)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(function, args) for args in arguments]
            try:
                for future in as_completed(futures):
                    yield future.result()
            except Exception:
                for future in futures:
                    future.cancel()
                raise


def _run_case(args):
    output, case = args
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    started = perf_counter()
    data = run_simulation(graph, {(0, 2): case["demand"]}, memory_slots=case["capacity"],
                          cutoff_time=None if case["scenario"] == "chain_lossless" else 10.0,
                          distillation_pairs=1, horizon=case["horizon"], seed=case["seed"],
                          ticks_per_time_unit=1000000, admission_policy="reserved",
                          swap_policy=case["policy"], record_events=True).to_dict()
    observed = observe_robustness(data, warmup=case["warmup"], split=case["split"])
    case = {**case, "simulation_and_observation_seconds": perf_counter() - started}
    # Return only small metadata across process boundaries, not the event inventory.
    payload = json.dumps({"case": case, "simulation": data, "observed": observed},
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(Path(output) / case["artifact"], "wb", compresslevel=1) as stream:
        stream.write(payload)
    return case


def run_suite(output, *, horizon=8000, warmup=500, split=2000, replicates=10, seed=5271, workers=3):
    validate_parameters(horizon, warmup, split, replicates, seed, workers)
    output = create_output(output)
    (output / "runs").mkdir()
    paths = (Path(__file__).resolve(), ROOT / "scripts/robustness_observations.py",
             ROOT / "scripts/memory_policy_analysis.py", ROOT / "scripts/verify_implementation_results.py",
             ROOT / "src/poqi/simulation/sequence_adapter.py", ROOT / "src/poqi/simulation/inventory.py",
             ROOT / "src/poqi/analysis/blocking.py")
    manifest = {**provenance(), "status": "running", "horizon": horizon, "warmup": warmup, "split": split,
                "seeds": list(range(seed, seed + replicates)), "scenarios": list(SCENARIOS),
                "demands": list(DEMANDS), "capacities": list(CAPACITIES), "policies": list(POLICIES),
                "memory_comparisons": [list(pair) for pair in MEMORY_COMPARISONS], "workers": workers,
                "compression": "gzip level 1; compact JSON", "runs": [],
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                "protocol": "D=1, empty three-node chain, generation1/link, reserved admission; frozen policies; fresh seeds matched across policies/capacities within each demand",
                "intervals": "Pointwise95% Student-t across independent seeds; policy, horizon and cross-capacity differences paired by seed; windows are correlated",
                "interpretation": "Finite-window evidence only; no stability, equivalence or globally minimal memory claim"}
    write_json(output / "manifest.json", manifest)
    cases = []
    for scenario, demand, capacity, run_seed, policy in product(SCENARIOS, DEMANDS, CAPACITIES, manifest["seeds"], POLICIES):
        label = "unlimited" if capacity is None else str(capacity)
        identifier = f"{scenario}-d{demand:g}-c{label}-s{run_seed}-{policy}"
        cases.append({"id": identifier, "scenario": scenario, "demand": demand, "capacity": capacity,
                      "seed": run_seed, "policy": policy, "horizon": horizon, "warmup": warmup, "split": split,
                      "artifact": f"runs/{identifier}.json.gz"})
    started = perf_counter()
    try:
        for case in _tasks(_run_case, [(str(output), case) for case in cases], workers):
            manifest["runs"].append(case)
            write_json(output / "manifest.json", manifest)
            print(f"Simulated {len(manifest['runs'])}/{len(cases)}: {case['id']}", flush=True)
        manifest.update(status="completed", simulation_wall_seconds=perf_counter() - started)
        write_json(output / "manifest.json", manifest)
    except Exception as error:
        manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(output / "manifest.json", manifest)
        raise
    return output


def _replay_case(args):
    source, case, windows = args
    path = (Path(source) / case["artifact"]).resolve()
    require(path.is_relative_to(Path(source).resolve() / "runs"), "artifact outside runs directory")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        saved = json.load(stream)
    require(saved["case"] == case, "manifest/case mismatch")
    data = saved["simulation"]
    require((case["horizon"], case["warmup"], case["split"]) == windows
            and data["horizon"] == case["horizon"] and data["seed"] == case["seed"], "window/seed mismatch")
    require(data["distillation_pairs"] == 1 and data["initial_pairs"] == 0
            and data["cutoff_time"] == (None if case["scenario"] == "chain_lossless" else 10.0)
            and data["swap_policy"] == case["policy"] and data["admission_policy"] == "reserved"
            and data["ticks_per_time_unit"] == 1000000 and data["time_unit"] == "abstract", "simulation protocol mismatch")
    require({r["node"] for r in data["occupancy_by_node"]} == {0, 1, 2}
            and all(r["memory_slots"] == case["capacity"] for r in data["occupancy_by_node"]), "node/capacity mismatch")
    require({tuple(r["endpoints"]): r["demand_rate"] for r in data["service_by_pair"]}
            == {(0, 2): case["demand"]}, "demand mismatch")
    require(all(set(e["created"][0]["endpoints"] if e["kind"] == "generate" else e["endpoints"])
                in ({0, 1}, {1, 2}) for e in data["events"] if e["kind"] in ("generate", "reject")),
            "generation topology mismatch")
    observed = observe_robustness(data, warmup=case["warmup"], split=case["split"])
    require(observed == saved["observed"], "saved metrics differ from event replay")
    return {**case, **observed}


def summarize_group(rows):
    require(bool(rows), "empty robustness group")
    return {"n": len(rows), **{f"{flag}_runs": sum(row[flag] for row in rows) for flag in FLAGS},
            "undefined_swap_ratios": sum(row["swaps_per_completion"] is None for row in rows),
            **{metric: interval([row[metric] for row in rows]) for metric in METRICS}}


def contrasts(left, right, metrics=METRICS):
    return {metric: paired_difference(left, right, metric) for metric in metrics}


def build_report(source, *, workers=1):
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "completed", "experiment is incomplete")
    seeds = manifest["seeds"]
    require(len(seeds) >= 2 and len(seeds) == len(set(seeds)) and all(type(s) is int and s >= 0 for s in seeds),
            "invalid or duplicate seeds")
    validate_parameters(manifest["horizon"], manifest["warmup"], manifest["split"], len(seeds), seeds[0], workers)
    require(all(manifest[key] == list(expected) for key, expected in
                (("scenarios", SCENARIOS), ("demands", DEMANDS), ("capacities", CAPACITIES), ("policies", POLICIES)))
            and manifest["memory_comparisons"] == [list(pair) for pair in MEMORY_COMPARISONS], "protocol coverage mismatch")
    key_of = lambda row: (row["scenario"], row["demand"], row["capacity"], row["seed"], row["policy"])
    expected = list(product(SCENARIOS, DEMANDS, CAPACITIES, seeds, POLICIES))
    keys = [key_of(case) for case in manifest["runs"]]
    require(len(keys) == len(set(keys)), "duplicate experiment case")
    require(set(keys) == set(expected), "missing or unexpected experiment cases")
    windows = (manifest["horizon"], manifest["warmup"], manifest["split"])
    cases, signatures = {}, {}
    arguments = [(str(source), case, windows) for case in manifest["runs"]]
    for row in _tasks(_replay_case, arguments, workers):
        key = key_of(row)
        match = row["demand"], row["seed"]
        require(match not in signatures or signatures[match] == row["input_signature"], "unmatched exogenous inputs")
        signatures[match] = row["input_signature"]
        cases[key] = row
        if len(cases) % 25 == 0 or len(cases) == len(expected):
            print(f"Replayed {len(cases)}/{len(expected)}", flush=True)
    report = {"source": str(source), "protocol": manifest["protocol"], "intervals": manifest["intervals"],
              "interpretation": manifest["interpretation"], "horizon": manifest["horizon"],
              "warmup": manifest["warmup"], "split": manifest["split"], "seeds": seeds,
              "validated_runs": len(cases), "unlimited_equivalent_pairs": 0,
              "summary": [], "paired": [], "horizon_changes": [], "memory_comparisons": [], "observations": []}
    for key in expected:
        case = cases[key]
        identity = {k: case[k] for k in ("scenario", "demand", "capacity", "policy", "seed", "artifact")}
        report["observations"].extend({**identity, **row} for row in case["windows"])
    rows_by_key = {}
    for row in report["observations"]:
        rows_by_key.setdefault((row["scenario"], row["demand"], row["capacity"], row["policy"], row["window"]), []).append(row)
    for scenario, demand in product(SCENARIOS, DEMANDS):
        for seed in seeds:
            left, right = (cases[scenario, demand, None, seed, policy] for policy in POLICIES)
            require(left["event_signature"] == right["event_signature"] and left["windows"] == right["windows"],
                    "unlimited pressure/balancing equivalence failed")
            report["unlimited_equivalent_pairs"] += 1
        for capacity in CAPACITIES:
            for window in WINDOWS:
                identity = {"scenario": scenario, "demand": demand, "capacity": capacity, "window": window}
                groups = {p: rows_by_key[scenario, demand, capacity, p, window] for p in POLICIES}
                for policy, rows in groups.items():
                    report["summary"].append({**identity, "policy": policy, **summarize_group(rows)})
                report["paired"].append({**identity, "policy": "pressure_relaxed", "reference": "balancing", "n": len(seeds),
                                          **contrasts(groups["pressure_relaxed"], groups["balancing"])})
            for policy in POLICIES:
                report["horizon_changes"].append({"scenario": scenario, "demand": demand, "capacity": capacity,
                    "policy": policy, "difference": "late minus early", "n": len(seeds),
                    **contrasts(rows_by_key[scenario, demand, capacity, policy, "late"],
                                rows_by_key[scenario, demand, capacity, policy, "early"], HORIZON_METRICS)})
        for pressure_capacity, balancing_capacity in MEMORY_COMPARISONS:
            for window in WINDOWS:
                report["memory_comparisons"].append({"scenario": scenario, "demand": demand, "window": window,
                    "pressure_capacity": pressure_capacity, "balancing_capacity": balancing_capacity,
                    "memory_reduction_fraction": 1 - pressure_capacity / balancing_capacity, "n": len(seeds),
                    **contrasts(rows_by_key[scenario, demand, pressure_capacity, "pressure_relaxed", window],
                                rows_by_key[scenario, demand, balancing_capacity, "balancing", window])})
    return report


def write_report(report, output):
    output = create_output(output)
    write_json(output / "robustness.json", report)
    for name in ("observations", "summary", "paired", "horizon_changes", "memory_comparisons"):
        rows = report[name]
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    labels = {"balancing": "Corrected balancing", "pressure_relaxed": "Pressure relaxation"}
    def errorbar(ax, rows, metric, offset, **kwargs):
        present = [(i, r[metric]) for i, r in enumerate(rows) if r[metric]["mean"] is not None]
        y = [r["mean"] for _, r in present]
        errors = [[r["mean"] - r["ci95"][0] for _, r in present], [r["ci95"][1] - r["mean"] for _, r in present]]
        ax.errorbar([i + offset for i, _ in present], y, yerr=errors, capsize=3, **kwargs)
    for window in WINDOWS:
        fig, axes = plt.subplots(6, 3, figsize=(14, 16), constrained_layout=True)
        for index, (scenario, demand) in enumerate(product(SCENARIOS, DEMANDS)):
            for offset, policy in enumerate(POLICIES):
                rows = [next(r for r in report["summary"] if r["scenario"] == scenario and r["demand"] == demand
                             and r["capacity"] == c and r["policy"] == policy and r["window"] == window) for c in CAPACITIES]
                for column, (metric, ylabel) in enumerate((("throughput", "Completions / time unit"),
                                                         ("blocking_probability", "Rejected generation fraction"),
                                                         ("backlog_growth_rate", "Net backlog growth / time unit"))):
                    ax = axes[index, column]
                    errorbar(ax, rows, metric, (offset - .5) * .07, fmt="o-", label=labels[policy])
                    ax.set(title=f"{'No expiry' if scenario == 'chain_lossless' else 'Cutoff 10'}, demand {demand:g}",
                           xlabel="Slots per node", ylabel=ylabel, xticks=range(len(CAPACITIES)),
                           xticklabels=["unlimited" if c is None else str(c) for c in CAPACITIES])
                    ax.grid(alpha=.2)
                    if column == 2:
                        ax.axhline(0, color="black", lw=.7)
                    if column == 0:
                        ax.axhline(demand, color="gray", lw=.8, linestyle=":")
            if index == 0:
                axes[index, 0].legend(fontsize=8)
        start, end = (report["warmup"], report["split"]) if window == "early" else (report["split"], report["horizon"])
        fig.suptitle(f"{window.capitalize()} window [{start:g}, {end:g}): means and pointwise95% t intervals")
        fig.savefig(output / f"{window}.png", dpi=150)
        plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), constrained_layout=True)
    for index, (scenario, demand) in enumerate(product(SCENARIOS, DEMANDS)):
        ax = axes[index // 3, index % 3]
        for offset, policy in enumerate(POLICIES):
            rows = [next(r for r in report["horizon_changes"] if r["scenario"] == scenario and r["demand"] == demand
                         and r["capacity"] == c and r["policy"] == policy) for c in CAPACITIES]
            errorbar(ax, rows, "throughput", (offset - .5) * .07, fmt="o-", label=labels[policy])
        ax.axhline(0, color="black", lw=.7)
        ax.set(title=f"{'No expiry' if scenario == 'chain_lossless' else 'Cutoff 10'}, demand {demand:g}",
               xlabel="Slots per node", ylabel="Late minus early throughput", xticks=range(len(CAPACITIES)),
               xticklabels=["unlimited" if c is None else str(c) for c in CAPACITIES])
        ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Horizon comparison: paired differences within each seed, 95% t intervals")
    fig.savefig(output / "horizon_changes.png", dpi=150)
    plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-runs", type=Path)
    parser.add_argument("--horizon", type=float, default=8000)
    parser.add_argument("--warmup", type=float, default=500)
    parser.add_argument("--split", type=float, default=2000)
    parser.add_argument("--replicates", type=int, default=10)
    parser.add_argument("--seed", type=int, default=5271)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.from_runs:
        output = write_report(build_report(args.from_runs, workers=args.workers), args.output)
    else:
        source = run_suite(args.output, horizon=args.horizon, warmup=args.warmup, split=args.split,
                           replicates=args.replicates, seed=args.seed, workers=args.workers)
        output = write_report(build_report(source, workers=args.workers), source / "report")
    print(f"Validated all robustness runs and wrote {output}", flush=True)


if __name__ == "__main__":
    main()

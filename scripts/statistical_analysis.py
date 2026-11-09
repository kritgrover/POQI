"""Summarize existing pilots with replicate confidence intervals and error bars."""

import argparse
import csv
import itertools
import json
import math
from pathlib import Path

try:
    from .verify_implementation_results import ROOT, DEFAULT, interval, require, verify_directory
except ImportError:  # Direct command-line execution.
    from verify_implementation_results import ROOT, DEFAULT, interval, require, verify_directory


MEMORY = ROOT / "results/memory/acceptance-chain-smoke"
METHOD = "Pilot; two-sided 95% Student-t intervals across independent replicates; paired differences use matched seeds"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(values, **labels):
    require(bool(values), "empty group")
    require(all(v is None or math.isfinite(v) for v in values), "nonfinite observation")
    estimate = interval(values)
    bounds = estimate["ci95"]
    return {**labels, "n": len(values), "n_defined": sum(v is not None for v in values),
            "mean": estimate["mean"], "ci_low": bounds[0] if bounds else None,
            "ci_high": bounds[1] if bounds else None,
            "status": "undefined_observations" if None in values else
                      "single_run_no_ci" if len(values) == 1 else "pilot"}


def comparison_statistics(directory):
    directory = Path(directory).resolve()
    checked = verify_directory(directory)
    manifest = read_json(directory / "manifest.json")
    records = [read_json(path) for path in sorted((directory / "runs").glob("*.json"))]
    indexed = {(r["replicate"], r["distillation_pairs"], r["dynamics"]): r for r in records}
    rows, seeds = [], []
    for i in range(manifest["replicates"]):
        tape = read_json(directory / "inputs" / f"input-{i:03d}.json")
        seeds.append({"experiment": directory.name, "replicate": i,
                      "master_seed": manifest["seed"], "graph_seed": tape["metadata"]["graph_seed"],
                      "input_seed": tape["seed"], "stream_seeds": tape["stream_seeds"]})
    require(len({s["input_seed"] for s in seeds}) == len(seeds), "duplicate comparison input seed")
    for d, metric in itertools.product(manifest["distillation_pairs"],
                                      ("total_pairs_consumed", "legacy_overhead", "corrected_overhead")):
        labels = dict(experiment=directory.name, D=d, metric=metric, horizon=manifest["horizon"],
                      time_unit="iteration", master_seed=manifest["seed"])
        groups = {}
        for dynamics in ("original", "corrected"):
            members = [indexed[i, d, dynamics] for i in range(manifest["replicates"])]
            groups[dynamics] = [r[metric] for r in members]
            rows.append(summarize(groups[dynamics], **labels, dynamics=dynamics,
                                  low_completion_runs=sum(not r["minimum_completed_met"] for r in members)))
        differences = [None if a is None or b is None else b - a
                       for a, b in zip(groups["original"], groups["corrected"])]
        rows.append(summarize(differences, **labels, dynamics="corrected-minus-original",
                              low_completion_runs=sum(not (indexed[i, d, "original"]["minimum_completed_met"]
                                                           and indexed[i, d, "corrected"]["minimum_completed_met"])
                                                      for i in range(manifest["replicates"]))))
    return rows, seeds, checked["validated_runs"]


def memory_statistics(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    require(manifest["status"] == "complete" and not manifest.get("failures"), "incomplete memory experiment")
    settings, config = manifest["sweep_settings"], manifest["configuration"]
    budgets, loads, reps = settings["memory_slots"], settings["demand_factors"], settings["replicates"]
    require(type(reps) is int and reps > 0 and None in budgets, "memory replicates/unlimited reference missing")
    require(bool(loads), "missing memory demand factors")
    require(len(set(budgets)) == len(budgets) and len(set(loads)) == len(loads), "duplicate memory condition")
    require(config["simulation"].get("swap_policy", "balancing") == "balancing", "memory report requires balancing policy")
    horizon = config["simulation"]["horizon"]
    require(horizon > 0, "invalid memory horizon")
    expected = set(itertools.product(loads, budgets, range(reps)))
    records, artifacts = {}, set()
    with (directory / "simulation.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            budget = float(row["memory_slots"]) if row["memory_slots"] else None
            load, replicate = float(row["demand_factor"]), int(row["replicate"])
            key = (load, budget, replicate)
            require(key in expected and key not in records, "unexpected or duplicate memory run")
            artifact = (directory / row["artifact"]).resolve()
            require(artifact.is_relative_to(directory), "memory artifact outside experiment")
            require(artifact not in artifacts, "duplicate memory artifact")
            artifacts.add(artifact)
            raw = read_json(artifact)
            require(row["status"] == raw["status"] == "completed", "failed memory run")
            require(int(row["seed"]) == raw["seed"] == settings["seed"] + replicate, "memory seed mismatch")
            require(raw["horizon"] == horizon, "memory horizon mismatch")
            require(raw["distillation_pairs"] == config["distillation_pairs"], "memory D mismatch")
            require(raw["time_unit"] == config["time_unit"], "memory time unit mismatch")
            for field, default in (("swap_policy", "balancing"), ("admission_policy", "reserved"), ("cutoff_time", None)):
                require(raw[field] == config["simulation"].get(field, default), f"memory {field} mismatch")
            require(raw["warmup"] == manifest["warmup"] == 0, "report expects full-window memory observations")
            require(raw["occupancy_by_node"] and all(r["memory_slots"] == budget for r in raw["occupancy_by_node"]),
                    "memory budget mismatch")
            value = float(row["throughput"])
            require(type(raw["completed_requests"]) is int and raw["completed_requests"] >= 0,
                    "invalid memory completion count")
            require(math.isfinite(value) and math.isclose(value, raw["throughput"], rel_tol=1e-12)
                    and math.isclose(value, raw["completed_requests"] / horizon, rel_tol=1e-12),
                    "memory throughput mismatch")
            records[key] = value
    require(set(records) == expected, "missing memory runs/partners")
    rows = []
    for load, budget in itertools.product(loads, budgets):
        labels = dict(experiment=directory.name, D=config["distillation_pairs"], demand_factor=load,
                      memory_slots=budget, metric="throughput", horizon=horizon,
                      time_unit=config["time_unit"], master_seed=settings["seed"])
        values = [records[load, budget, i] for i in range(reps)]
        rows.append(summarize(values, **labels, dynamics="balancing"))
        if budget is not None:
            rows.append(summarize([value - records[load, None, i] for i, value in enumerate(values)],
                                  **labels, dynamics="finite-minus-unlimited"))
    seeds = [{"experiment": directory.name, "replicate": i, "master_seed": settings["seed"],
              "input_seed": settings["seed"] + i} for i in range(reps)]
    return rows, seeds, len(records)


def build_report(comparison_directories=None, memory_directory=None):
    directories = [Path(p).resolve() for p in (comparison_directories if comparison_directories is not None
                                             else [DEFAULT / "cycle", DEFAULT / "grid"])]
    require(len(set(directories)) == len(directories), "duplicate comparison directory")
    require(len({p.name for p in directories}) == len(directories), "duplicate comparison experiment name")
    report = {"method": METHOD, "warmup": 0, "comparison": [], "memory": [], "seeds": [],
              "sources": [str(p) for p in directories], "validated_comparison_runs": 0}
    for directory in directories:
        rows, seeds, count = comparison_statistics(directory)
        report["comparison"].extend(rows)
        report["seeds"].extend(seeds)
        report["validated_comparison_runs"] += count
    memory_directory = Path(memory_directory if memory_directory is not None else MEMORY).resolve()
    report["memory"], seeds, report["validated_memory_runs"] = memory_statistics(memory_directory)
    report["seeds"].extend(seeds)
    report["sources"].append(str(memory_directory))
    return report


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
                         for key, value in row.items()} for row in rows)


def plot_report(report, output):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    colors = {"original": "#737373", "corrected": "#146C94"}
    labels = {"original": "Released", "corrected": "Corrected"}
    experiments = list(dict.fromkeys(r["experiment"] for r in report["comparison"] if r["D"] == 1))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), constrained_layout=True)
    for ax, metric, title in zip(axes, ("total_pairs_consumed", "corrected_overhead"),
                               ("Completed requests", "Swap overhead")):
        for j, dynamics in enumerate(colors):
            for i, experiment in enumerate(experiments):
                row = next(r for r in report["comparison"] if r["experiment"] == experiment and r["D"] == 1
                           and r["metric"] == metric and r["dynamics"] == dynamics)
                if row["mean"] is not None:
                    error = None if row["ci_low"] is None else [[row["mean"] - row["ci_low"]], [row["ci_high"] - row["mean"]]]
                    ax.errorbar(i + (j - 0.5) * 0.18, row["mean"], yerr=error, fmt="o", capsize=5,
                                color=colors[dynamics], label=labels[dynamics] if i == 0 else None)
        ax.set(xticks=range(len(experiments)), xticklabels=experiments, ylabel=title, title=title)
        ax.grid(axis="y", alpha=0.2)
        ax.legend()
    n_values = sorted({r["n"] for r in report["comparison"]})
    fig.suptitle(f"D=1 pilot: means and 95% t confidence intervals (n={','.join(map(str, n_values))})")
    fig.savefig(output / "comparison_d1.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.2, 4.6), constrained_layout=True)
    budgets = list(dict.fromkeys(r["memory_slots"] for r in report["memory"]))
    time_unit = report["memory"][0]["time_unit"]
    for load in sorted({r["demand_factor"] for r in report["memory"]}):
        rows = [r for r in report["memory"] if r["demand_factor"] == load and r["dynamics"] == "balancing"]
        x, y = [budgets.index(r["memory_slots"]) for r in rows], [r["mean"] for r in rows]
        errors = None if any(r["ci_low"] is None for r in rows) else [[r["mean"] - r["ci_low"] for r in rows],
                                                                   [r["ci_high"] - r["mean"] for r in rows]]
        ax.errorbar(x, y, yerr=errors, fmt="o-", capsize=5, label=f"Demand x{load}; n={rows[0]['n']}")
    ax.set(xticks=range(len(budgets)), xticklabels=["Unlimited" if b is None else str(b) for b in budgets],
           xlabel="Hard slots per node", ylabel=f"Completed requests / {time_unit} time unit",
           title="Memory pilot: means and 95% t confidence intervals")
    ax.grid(axis="y", alpha=0.2)
    ax.legend()
    fig.savefig(output / "memory_throughput.png", dpi=180)
    plt.close(fig)


def write_report(report, output):
    output = Path(output).resolve()
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "statistics.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name in ("comparison", "memory", "seeds"):
        write_csv(output / f"{name}.csv", report[name])
    plot_report(report, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", nargs="+", type=Path)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "results/statistics/pilot")
    args = parser.parse_args()
    try:
        report = build_report(args.comparison, args.memory)
        output = write_report(report, args.output)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Statistical report failed: {error}\n")
    print(f"Wrote {output}; validated {report['validated_comparison_runs']} comparison and "
          f"{report['validated_memory_runs']} memory runs; {METHOD}")


if __name__ == "__main__":
    main()

"""Report higher-D completions and right-censored first-completion observations."""

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path

from scipy.stats import norm

try:
    from .verify_implementation_results import interval, require, verify_directory
except ImportError:
    from verify_implementation_results import interval, require, verify_directory


def wilson(successes, n):
    require(type(n) is int and n > 0 and type(successes) is int and 0 <= successes <= n,
            "invalid completion fraction counts")
    p, z = successes / n, float(norm.ppf(0.975))
    scale = 1 + z * z / n
    center = (p + z * z / (2 * n)) / scale
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / scale
    return p, max(0.0, center - half), min(1.0, center + half)


def first_observation(row):
    require("first_completion_step" in row, "missing first_completion_step measurement")
    first, horizon, count = row["first_completion_step"], row["horizon"], row["total_pairs_consumed"]
    require(type(horizon) is int and horizon > 0, "invalid observation horizon")
    require(type(count) is int and count >= 0, "invalid completion count")
    require(row["finished"] and row["stop_reason"] == "fixed_horizon", "unfinished observation")
    require((first is None and count == 0) or
            (type(first) is int and 0 <= first <= horizon and count > 0), "inconsistent first completion")
    return {"first_completion_step": first, "observation_step": horizon if first is None else first,
            "completion_observed": first is not None, "right_censored": first is None}


def summarize_group(records):
    require(bool(records), "empty group")
    horizon = records[0]["horizon"]
    require(all(r["horizon"] == horizon for r in records), "mixed observation horizons")
    observations = [first_observation(r) for r in records]
    counts = [r["total_pairs_consumed"] for r in records]
    successes = sum(o["completion_observed"] for o in observations)
    fraction, low, high = wilson(successes, len(records))
    result = {"n": len(records), "runs_with_completion": successes, "censored_runs": len(records) - successes,
              "completion_fraction": fraction, "completion_fraction_ci_low": low, "completion_fraction_ci_high": high,
              "low_completion_runs": sum(not r["minimum_completed_met"] for r in records),
              "undefined_overhead_runs": sum(r["corrected_overhead"] is None for r in records)}
    for name, values in (("completions", counts), ("completion_rate", [q / horizon for q in counts]),
                         ("restricted_first", [o["observation_step"] for o in observations])):
        estimate = interval(values)
        bounds = estimate["ci95"]
        result.update({f"{name}_mean": estimate["mean"],
                       f"{name}_ci_low": bounds[0] if bounds else None,
                       f"{name}_ci_high": bounds[1] if bounds else None})
    return result


def prefix_record(row, point, horizon, minimum_completed):
    """A shorter window of the same trajectory, including censoring at that window."""
    first_observation(row)
    counts = {key: int(point[key]) for key in
              ("total_pairs_consumed", "total_generated", "total_swaps", "remaining_inventory")}
    require(all(v >= 0 for v in counts.values()), "negative checkpoint count")
    require(all(counts[key] <= row[key] for key in ("total_pairs_consumed", "total_generated", "total_swaps")),
            "checkpoint exceeds final totals")
    require(counts["remaining_inventory"] == row["initial_inventory"] + counts["total_generated"]
            - (2 * row["distillation_pairs"] - 1) * counts["total_swaps"]
            - row["distillation_pairs"] * counts["total_pairs_consumed"], "checkpoint conservation mismatch")
    first = row["first_completion_step"]
    overhead = point["corrected_overhead"]
    denominator = int(point["corrected_denominator"])
    require(denominator >= 0 and (not overhead if denominator == 0 else
            bool(overhead) and math.isclose(float(overhead), counts["total_swaps"] / denominator, rel_tol=1e-12)),
            "checkpoint overhead mismatch")
    if horizon == row["horizon"]:
        require(all(value == row[key] for key, value in counts.items())
                and denominator == row["corrected_denominator"], "final checkpoint mismatch")
    return {**row, **counts, "horizon": horizon,
            "first_completion_step": first if first is not None and first <= horizon else None,
            "minimum_completed_met": counts["total_pairs_consumed"] >= minimum_completed,
            "corrected_overhead": float(overhead) if overhead else None}


def build_report(directories, horizons=None):
    directories = [Path(p).resolve() for p in directories]
    require(directories and len(set(directories)) == len(directories), "missing or duplicate input directory")
    require(len({p.name for p in directories}) == len(directories), "duplicate experiment name")
    require(horizons is None or (horizons and all(type(h) is int and h > 0 for h in horizons)
                                and len(set(horizons)) == len(horizons)), "invalid or duplicate horizons")
    report = {"method": "Fixed-horizon pilot; 95% Student-t intervals across runs; 95% Wilson intervals for run completion fractions",
              "first_completion": "No-completion runs are right-censored at H; restricted_first estimates E[min(T_first,H)], not E[T_first] or a success-only mean",
              "time_unit": "iteration", "sources": [str(p) for p in directories],
              "rate_axis": "Symlog; linear within +/-1/H, retaining zero and negative approximate confidence bounds",
              "prefix_note": "Requested horizons are correlated windows of the same trajectories, not extra independent repetitions",
              "validated_runs": 0, "summary": [], "observations": [], "seeds": []}
    for directory in directories:
        checked = verify_directory(directory)
        windows = sorted(horizons) if horizons is not None else [checked["horizon"]]
        require(max(windows) <= checked["horizon"], "requested horizon exceeds recorded run")
        points = {}
        if horizons is not None:
            with (directory / "checkpoints.csv").open(newline="", encoding="utf-8") as stream:
                for point in csv.DictReader(stream):
                    key = (int(point["replicate"]), int(point["distillation_pairs"]), point["dynamics"], int(point["step"]))
                    require(key not in points, "duplicate checkpoint")
                    points[key] = point
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        report["validated_runs"] += checked["validated_runs"]
        groups = defaultdict(list)
        for path in sorted((directory / "runs").glob("*.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            for horizon in windows:
                observed = row
                if horizons is not None:
                    key = (row["replicate"], row["distillation_pairs"], row["dynamics"], horizon)
                    require(key in points, f"missing checkpoint: {key}")
                    observed = prefix_record(row, points[key], horizon, manifest["minimum_completed_requests"])
                groups[row["distillation_pairs"], row["dynamics"], horizon].append(observed)
                report["observations"].append({"experiment": directory.name, "D": row["distillation_pairs"],
                    "dynamics": row["dynamics"], "replicate": row["replicate"], "horizon": horizon,
                    "completed_requests": observed["total_pairs_consumed"], **first_observation(observed)})
        for (d, dynamics, horizon), rows in sorted(groups.items()):
            report["summary"].append({"experiment": directory.name, "D": d, "dynamics": dynamics,
                                      "horizon": horizon, **summarize_group(rows)})
        for i in range(checked["replicates"]):
            tape = json.loads((directory / "inputs" / f"input-{i:03d}.json").read_text(encoding="utf-8"))
            report["seeds"].append({"experiment": directory.name, "replicate": i, "master_seed": checked["master_seed"],
                                    "graph_seed": tape["metadata"]["graph_seed"], "input_seed": tape["seed"]})
    return report


def write_report(report, output):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    output = Path(output).resolve()
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "scaling.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name in ("summary", "observations", "seeds"):
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(report[name][0]))
            writer.writeheader()
            writer.writerows(report[name])
    panels = list(dict.fromkeys((r["experiment"], r["horizon"]) for r in report["summary"]))
    fig, axes = plt.subplots(len(panels), 2, squeeze=False,
                             figsize=(10, 3.6 * len(panels)), constrained_layout=True)
    for row_index, (experiment, horizon) in enumerate(panels):
        for offset, (dynamics, color, label) in enumerate((("original", "#777777", "Released"),
                                                         ("corrected", "#146C94", "Corrected"))):
            rows = sorted((r for r in report["summary"] if r["experiment"] == experiment
                           and r["horizon"] == horizon and r["dynamics"] == dynamics), key=lambda r: r["D"])
            for ax, metric, title in ((axes[row_index, 0], "completion_rate", "Completed requests / iteration"),
                                      (axes[row_index, 1], "completion_fraction", "Fraction of runs with any completion")):
                mean_key = "completion_rate_mean" if metric == "completion_rate" else metric
                y = [r[mean_key] for r in rows]
                error = None if any(r[f"{metric}_ci_low"] is None for r in rows) else [
                    [max(0, v - r[f"{metric}_ci_low"]) for r, v in zip(rows, y)],
                    [max(0, r[f"{metric}_ci_high"] - v) for r, v in zip(rows, y)]]
                ax.errorbar([r["D"] + (offset - .5) * .08 for r in rows], y, yerr=error,
                            fmt="o-", capsize=4, color=color, label=label)
                ax.set(xlabel="D", ylabel=title, xticks=[r["D"] for r in rows],
                       title=f"{experiment}: H={rows[0]['horizon']:,}, n={rows[0]['n']}")
                ax.grid(axis="y", alpha=.2)
            axes[row_index, 1].set_ylim(-.03, 1.03)
        axes[row_index, 0].legend()
        axes[row_index, 0].set_yscale("symlog", linthresh=1 / horizon)
        axes[row_index, 0].set_ylabel("Completions / iteration (symlog)")
    fig.suptitle("Higher-D pilot: 95% t intervals (rates), 95% Wilson intervals (fractions)")
    fig.savefig(output / "scaling.png", dpi=180)
    plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--horizons", nargs="+", type=int, help="Checkpoint horizons from the same recorded trajectories")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.directories, args.horizons)
        output = write_report(report, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Scaling report failed: {error}\n")
    print(f"Wrote {output}; validated {report['validated_runs']} runs; censored observations retained")


if __name__ == "__main__":
    main()

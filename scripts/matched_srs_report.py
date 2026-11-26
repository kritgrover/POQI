"""Verify the paired design, compute its tables, and render its primary figure."""

import argparse
import csv
import gzip
import json
import math
from pathlib import Path
import statistics

from scipy.stats import t

from scripts.matched_srs import ARMS, Scenario, source_digest, ROOT


METRICS = ("core.satisfaction", "core.minimum_satisfaction", "core.restricted_wait",
           "core.longest_gap", "core.gap_p95", "core.outage_share", "core.unfinished_fraction",
           "core.end_backlog", "core.starved_classes", "background.offered",
           "background.restricted_wait", "background.unfinished_fraction", "drops_per_completion",
           "swaps_per_completion", "attempts_per_completion", "expired_per_completion")
COMPARISONS = (("pre_drop", "srs50"), ("pre_drop", "pressure"), ("pre_drop", "post_drop"),
               ("pre_drop", "srs25"), ("pre_drop", "srs100"))


def estimate(values):
    if not values:
        return {"n": 0, "mean": None, "lower": None, "upper": None}
    avg = statistics.fmean(values)
    half = (t.ppf(0.975, len(values)-1) * statistics.stdev(values) / math.sqrt(len(values))
            if len(values) >= 2 else None)
    return {"n": len(values), "mean": avg, "lower": avg-half if half is not None else None,
            "upper": avg+half if half is not None else None}


def observations(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["source_sha256_lf"].items():
        if source_digest(ROOT/name) != expected:
            raise ValueError(f"source fingerprint mismatch for {name}")
    data = {}
    with gzip.open(directory / "runs.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key = (row["cell"], row["arm"], row["seed"])
            if key in data:
                raise ValueError(f"duplicate trajectory {key}")
            data[key] = row
    arms = [arm[0] for arm in manifest["arms"]]
    expected = {(cell, arm, seed) for cell in manifest["cells"]
                for arm in arms for seed in manifest["seeds"]}
    if set(data) != expected or len(data) != manifest["rows"]:
        raise ValueError("the release has incomplete trajectory coverage")
    for cell in manifest["cells"]:
        for seed in manifest["seeds"]:
            signatures = {data[cell, arm, seed]["input_sha256"] for arm in arms}
            if len(signatures) != 1:
                raise ValueError(f"unpaired external inputs in {cell}, seed {seed}")
    return manifest, data


def value(row, key):
    cost = {"swaps_per_completion": "swaps", "attempts_per_completion": "attempts",
            "expired_per_completion": "expired"}.get(key)
    if cost:
        n = row["total_completed"]
        return row["counts"].get(cost, 0) / n if n else None
    for part in key.split("."):
        row = row[part]
    return row


def write_table(path, records):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def build_tables(manifest, data):
    cells, contrasts, support = [], [], []
    seeds = manifest["seeds"]
    for cell in manifest["cells"]:
        for arm, _, _ in ARMS:
            for metric in METRICS:
                values = [value(data[cell, arm, seed], metric) for seed in seeds]
                cells.append({"cell": cell, "arm": arm, "metric": metric,
                              **estimate([v for v in values if v is not None])})
        for left, right in COMPARISONS:
            for metric in METRICS:
                pairs = [(value(data[cell, left, s], metric), value(data[cell, right, s], metric)) for s in seeds]
                contrasts.append({"cell": cell, "left": left, "right": right, "metric": metric,
                                  **estimate([a-b for a, b in pairs if a is not None and b is not None])})
        parameters = manifest["cells"][cell]
        if parameters["background"]:
            baseline = Scenario(**{**parameters, "background": 0.0}).name
            for arm, _, _ in ARMS:
                for metric in ("core.satisfaction", "core.restricted_wait", "core.longest_gap", "core.outage_share"):
                    delta = [value(data[cell, arm, s], metric) - value(data[baseline, arm, s], metric)
                             for s in seeds]
                    support.append({"cell": cell, "comparison": baseline, "arm": arm, "metric": metric,
                                    **estimate(delta)})
    return cells, contrasts, support


def figure(directory, cells):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    primary = Scenario().name
    rows = {(r["arm"], r["metric"]): r for r in cells if r["cell"] == primary}
    arms = [a[0] for a in ARMS]
    names = ["SRS 0.25", "SRS 0.50", "SRS 1.00", "Pressure", "Pre-attempt eviction", "Post-success eviction"]
    fig, axes = plt.subplots(1, 2, figsize=(8.3, 3.6), sharey=True)
    for ax, metric, label in zip(axes, ("core.satisfaction", "core.restricted_wait"),
                                  ("Core completions / nominal arrivals", "Restricted mean wait (slots; cap 50)")):
        for y, arm in enumerate(arms):
            entry = rows[arm, metric]
            mean = entry["mean"]
            ax.errorbar(mean, y, xerr=[[mean-entry["lower"]], [entry["upper"]-mean]],
                        color="#a64414" if arm == "pre_drop" else "#235779", fmt="o", capsize=3)
        ax.set_xlabel(label, fontsize=9)
        ax.grid(axis="x", alpha=.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.xaxis.set_major_locator(MaxNLocator(5))
    axes[0].set_yticks(range(len(arms)), names)
    axes[0].invert_yaxis()
    fig.suptitle("Eight-node cycle with two slots per node", fontsize=13)
    fig.subplots_adjust(left=.22, bottom=.19, right=.98, top=.85, wspace=.19)
    fig.savefig(directory/"primary.pdf", metadata={"CreationDate": None, "ModDate": None})
    fig.savefig(directory/"primary.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest, data = observations(args.directory)
    summaries, contrasts, support = build_tables(manifest, data)
    write_table(args.directory / "cells.csv", summaries)
    write_table(args.directory / "paired.csv", contrasts)
    write_table(args.directory / "background-sensitivity.csv", support)
    figure(args.directory, summaries)
    print(f"Verified and summarized {len(data)} trajectories in {len(manifest['cells'])} cells.")


if __name__ == "__main__":
    main()

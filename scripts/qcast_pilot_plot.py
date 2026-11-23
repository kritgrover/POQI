"""Export the complete predeclared pilot grid with seed-level intervals."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


STYLES = {
    "QCAST-Slot-FIFO": ("Q-CAST · slot/FIFO", "#b45309", "o", "-"),
    "POQI-Slot-balancing": ("Balancing · reset", "#9ca3af", "s", "--"),
    "POQI-Slot-pressure_relaxed": ("Pressure · reset", "#0891b2", "^", "--"),
    "POQI-Persistent-balancing": ("Balancing · persistent", "#4b5563", "D", ":"),
    "POQI-Persistent-pressure_relaxed": ("Pressure · persistent", "#1d4ed8", "o", "-"),
    "POQI-Cutoff10-balancing": ("Balancing · cutoff 10", "#a855f7", "v", ":"),
    "POQI-Cutoff10-pressure_relaxed": ("Pressure · cutoff 10", "#15803d", "x", "--"),
}


def export(directory):
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_text())
    output = directory / "figures"
    output.mkdir(exist_ok=False)
    rows = []
    for group in report["summaries"]:
        for metric, value in group.items():
            if isinstance(value, dict):
                rows.append({"topology": group["topology"], "memory": group["memory"],
                             "p": group["p"], "arm": group["arm"], "metric": metric, **value})
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5), sharey=True)
    for ax, (name, p) in zip(axes.flat, [("chain", 1.0), ("chain", .5), ("diamond", 1.0), ("diamond", .5)]):
        for arm, (label, color, marker, style) in STYLES.items():
            groups = sorted((g for g in report["summaries"] if g["topology"] == name and g["p"] == p and g["arm"] == arm),
                            key=lambda g: g["memory"])
            ax.errorbar([g["memory"] for g in groups], [g["throughput"]["mean"] for g in groups],
                        yerr=[[g["throughput"]["mean"]-g["throughput"]["low"] for g in groups],
                              [g["throughput"]["high"]-g["throughput"]["mean"] for g in groups]],
                        label=label, color=color, marker=marker, linestyle=style, linewidth=1.65,
                        markersize=5, capsize=3, alpha=.9)
        ax.axhline(.75 if name == "chain" else .9, color="#94a3b8", linestyle=(0, (2, 4)), linewidth=1)
        ax.set_title(f"{name.title()} · link success {p:g}", loc="left", fontweight="bold", fontsize=12)
        ax.set_xticks([2, 3, 4] if name == "chain" else [2, 4])
        ax.set_xlim(1.8, 4.2)
        ax.set_ylim(-.04, 1.02)
        ax.set_xlabel("Memory slots per node")
        ax.set_ylabel("Useful requests completed / time unit")
        ax.grid(axis="y", color="#e5e7eb", linewidth=.7)
        ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, fontsize=9, bbox_to_anchor=(.5, .025))
    fig.suptitle("Matched physical opportunities: results depend on storage and service rules", fontsize=15, fontweight="bold", x=.07, ha="left", y=.98)
    fig.text(.07, .94, "Ten paired seeds · 400-slot runs · service window (100, 400] · pointwise 95% t intervals", fontsize=10, color="#475569")
    fig.text(.07, .005, "All primary arms use global FIFO. Q-CAST diamond zeros expose a scheduling interaction; they are not a claim of no routable paths.", fontsize=9, color="#475569")
    fig.tight_layout(rect=(.02, .12, .99, .92))
    fig.savefig(output / "throughput.png", dpi=170)
    fig.savefig(output / "throughput.pdf")
    plt.close(fig)
    print(output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    export(parser.parse_args().directory)

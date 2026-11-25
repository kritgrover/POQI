"""Plot paired guard effects from the fresh cohort of the matched diamond study."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot(directory):
    rows = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    fresh = {(r["memory"], r["p"], r["cutoff"]): r for r in rows
             if r["group"] == "fresh" and r["scope"] == "all"}
    conditions = [(2, 0.5), (4, 0.5), (4, 1.0)]
    metrics = [("throughput", "Completions per slot"), ("mean_backlog", "Mean requests waiting"),
               ("longest_gap", "Longest service gap (slots)")]
    fig, axes = plt.subplots(1, 3, figsize=(11.8, 3.65), sharey=True)
    fig.subplots_adjust(left=0.16, right=0.985, top=0.72, bottom=0.26, wspace=0.24)
    fig.text(0.03, 0.93, "Effect of the orientation rule on diamond service",
             fontsize=15, weight="bold", color="#1d2c38")
    fig.text(0.03, 0.84, "Change from unguarded pressure on matched inputs. "
             "Each link trial succeeds with probability p.",
             fontsize=10, color="#3c4b55")
    for ax, (key, label) in zip(axes, metrics):
        ax.set_title(label, fontsize=10, weight="bold", pad=8)
        ax.axvline(0, color="#76858d", lw=1.1, zorder=1)
        for cutoff, legend, marker, color, offset in [
                (None, "No expiry", "o", "#0b6374", 0.105),
                (10, "Cutoff of 10 slots", "s", "#b95123", -0.105)]:
            for i, (memory, probability) in enumerate(conditions):
                interval = fresh[memory, probability, cutoff][key]["paired_change"]
                mean = interval["mean"]
                ax.errorbar(mean, len(conditions)-1-i+offset,
                            xerr=[[mean-interval["low"]], [interval["high"]-mean]],
                            capsize=3, marker=marker, ms=5, color=color, lw=1.4,
                            label=legend if i == 0 else None)
        ax.set_ylim(-0.45, 2.45)
        ax.set_yticks([2, 1, 0], ["2 slots, p = 0.5", "4 slots, p = 0.5", "4 slots, p = 1"])
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#adb9bf")
        ax.tick_params(axis="y", length=0, pad=8)
        ax.tick_params(axis="x", labelsize=9)
        ax.grid(axis="y", alpha=0.17)
        ax.margins(x=0.13)
    axes[0].legend(loc="upper left", bbox_to_anchor=(-0.62, -0.22), ncol=2,
                   frameon=False, fontsize=9)
    fig.text(0.03, 0.025,
             "Ten fresh paired seeds per point. Bars show pointwise 95% t intervals. "
             "Gaps count time with demand waiting, clipped to the 300-slot window.",
             fontsize=9, color="#3c4b55")
    fig.savefig(directory / "guard_tradeoff.png", dpi=170, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    plot(parser.parse_args().directory)

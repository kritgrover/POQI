"""Render the fixed-order inventory and already archived paired holdout data."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle


ROOT = Path(__file__).resolve().parents[1]
ARMS = ("pre_drop", "pre_drop_shuffle", "srs50")
INK, NAVY, RUST, GRAY = "#202a32", "#255674", "#a7461c", "#a3acb1"


def archived_observations(directory):
    holdout = directory / "holdout"
    manifest = json.loads((holdout / "manifest.json").read_text(encoding="utf-8"))
    source = holdout / "seeds.csv"
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["sha256"]["seeds.csv"]:
        raise ValueError("The held-out dataset differs from its release manifest.")
    with source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_seed = {}
    for row in rows:
        seed, arm = int(row["seed"]), row["arm"]
        if arm in by_seed.setdefault(seed, {}):
            raise ValueError("Duplicate held-out observation.")
        by_seed[seed][arm] = float(row["satisfaction"])
    if set(by_seed) != set(range(13101, 13113)) or any(set(row) != set(ARMS) for row in by_seed.values()):
        raise ValueError("Expected the complete, three-arm, 12-seed held-out cohort.")
    return by_seed


def draw_inventory(ax):
    pos = {i: (math.cos(math.pi - i * math.pi / 4), math.sin(math.pi - i * math.pi / 4))
           for i in range(8)}

    def segment(u, v, **style):
        ax.plot(*zip(pos[u], pos[v]), **style)

    for u in range(8):
        segment(u, (u + 1) % 8, color=GRAY, lw=1.25)
    for u, v in ((5, 6), (6, 7)):
        segment(u, v, color=NAVY, lw=3.2, solid_capstyle="round")
    segment(5, 7, color=RUST, lw=2.1, ls=(0, (3, 1.7)))
    ax.text(0, -.53, "6-link pair", color=RUST, ha="center", va="center", fontsize=8)
    for node, (x, y) in pos.items():
        ax.add_patch(Circle((x, y), .139, edgecolor=INK, facecolor="white", lw=1, zorder=3))
        ax.text(x, y, str(node), color=INK, fontsize=8.2, ha="center", va="center", zorder=4)
    ax.set(xlim=(-1.18, 1.18), ylim=(-1.18, 1.18), aspect="equal")
    ax.axis("off")


def draw_outcomes(ax, data):
    seeds = sorted(data)
    values = [[data[s][a] for a in ARMS] for s in seeds]
    centers = range(len(ARMS))
    for i, row in enumerate(values):
        # Keep a seed's horizontal offset fixed across arms to separate the 12
        # identical zeros while retaining the within-seed connections.
        offset = .40 * (i / (len(seeds) - 1) - .5)
        ax.plot([x + offset for x in centers], row, color="#82949e", lw=.58, alpha=.61, zorder=2)
        for j, y in enumerate(row):
            ax.scatter(j + offset, y, s=13, facecolor="white", edgecolor=NAVY, lw=.72, zorder=3)
    arm_means = [mean(data[seed][arm] for seed in seeds) for arm in ARMS]
    for j, y in enumerate(arm_means):
        # An offset solid dash indicates the mean without hiding the seed dots.
        ax.plot([j+.235, j+.335], [y, y], color=INK, lw=2, solid_capstyle="butt", zorder=4)
    ax.axhline(1, color="#737d82", lw=.75, ls=(0, (3, 3)), zorder=1)
    lower = min(0, min(min(row) for row in values))
    upper = max(1, max(max(row) for row in values))
    ax.set(xlim=(-.29, 2.38), ylim=(lower-.045, upper+.065))
    ax.set_xticks(centers, ("Fixed order\npressure + drop", "Shuffled order\npressure + drop", "SRS\n$q=0.5$"))
    ax.set_yticks((0, .25, .5, .75, 1), ("0", "0.25", "0.50", "0.75", "1.00"))
    ax.set_ylabel("Core completions / nominal arrivals", fontsize=8.3, labelpad=4)
    ax.tick_params(axis="x", length=0, pad=5)
    ax.tick_params(axis="y", length=2.5, width=.65, pad=3)
    ax.grid(axis="y", color="#e2e6e8", lw=.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_linewidth(.6)
        ax.spines[spine].set_color("#8c969b")
    return arm_means


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT/"evidence/matched-lossless")
    args = parser.parse_args()
    data = archived_observations(args.directory)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
                         "pdf.fonttype": 42})
    fig = plt.figure(figsize=(7.12, 3.25), facecolor="white")
    diagram = fig.add_axes((.052, .236, .328, .60))
    chart = fig.add_axes((.523, .291, .455, .54))
    draw_inventory(diagram)
    means = draw_outcomes(chart, data)
    fig.text(.033, .932, "(a)  First fixed-order sweep", fontsize=10.2, weight="bold")
    fig.text(.451, .932, "(b)  Service across 12 held-out seeds", fontsize=10.2, weight="bold")
    fig.legend(
        [Line2D([], [], color=GRAY, lw=1.3), Line2D([], [], color=NAVY, lw=3),
         Line2D([], [], color=RUST, lw=2, ls=(0, (3, 1.7)))],
        ["Physical channel", "Stored elementary pair", "Stored virtual pair"],
        loc="lower left", bbox_to_anchor=(.035, .035), frameon=False, fontsize=7.2,
        handlelength=2.4, handletextpad=.65, labelspacing=.29, borderpad=0,
    )
    fig.text(.525, .092, "Lines connect observations from the same seed.", fontsize=7.3)
    fig.text(.525, .045, "Mean markers", fontsize=7.3, color=INK)
    fig.add_artist(Line2D([.631, .652], [.052, .052], transform=fig.transFigure, lw=2, color=INK))
    fig.text(.663, .045, "  /  ".join(f"{v:.3f}" for v in means), fontsize=7.3)
    fig.savefig(args.directory/"heldout-order.pdf", metadata={"CreationDate": None, "ModDate": None})
    fig.savefig(args.directory/"heldout-order.png", dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    main()

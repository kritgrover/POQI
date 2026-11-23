"""Export bounded concurrent-service figures and complete seed-level summaries.

This is a read-only consumer of a passed run. Pointwise 95% t intervals are
across seeds. Late throughput divided by nominal offered rate and the fraction
of all offered requests completed by the horizon are distinct CSV metrics.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.stats import t as student_t


ARMS = ("QCAST-Slot", "POQI-Slot-balancing", "POQI-Slot-pressure_relaxed",
        "POQI-Persistent-balancing", "POQI-Persistent-pressure_relaxed",
        "POQI-Cutoff10-balancing", "POQI-Cutoff10-pressure_relaxed")
LABELS = ("Q-CAST · slot", "Balancing · slot reset", "Pressure · slot reset",
          "Balancing · persistent", "Pressure · persistent", "Balancing · cutoff 10", "Pressure · cutoff 10")
SHORT_LABELS = ("Q-CAST", "Slot B", "Slot P", "Persist B", "Persist P", "Cut10 B", "Cut10 P")
COLORS = ("#166aa3", "#788493", "#17856b", "#788493", "#17856b", "#788493", "#17856b")
PAIRS = {(0, 3): .5, (0, 1): .25, (1, 2): .15}
CONDITIONS = ((2, 1.0), (2, .5), (4, 1.0), (4, .5))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def interval(values):
    defined = [value for value in values if value is not None]
    if not defined:
        return {"mean": None, "low": None, "high": None, "n": 0, "undefined": len(values)}
    mean = statistics.mean(defined)
    half = student_t.ppf(.975, len(defined)-1)*statistics.stdev(defined)/math.sqrt(len(defined)) if len(defined)>1 else None
    return {"mean": mean, "low": None if half is None else mean-half,
            "high": None if half is None else mean+half, "n": len(defined), "undefined": len(values)-len(defined)}


def load_inputs(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "passed":
        raise ValueError("plots require a successfully completed run")
    for name in ("observations.json", "report.json"):
        if digest(directory / name) != manifest["artifact_hashes"][name]:
            raise ValueError(f"changed report input: {name}")
    observations = json.loads((directory / "observations.json").read_text(encoding="utf-8"))
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    groups = {}
    for row in observations:
        key = tuple(row[k] for k in ("topology", "memory", "p", "arm", "service_mode"))
        group = groups.setdefault(key, {})
        if row["seed"] in group:
            raise ValueError("duplicate observation seed")
        group[row["seed"]] = row
    expected = {("diamond", memory, p, arm, mode)
                for memory, p in CONDITIONS for arm in ARMS for mode in ("fifo", "concurrent_per_pair")}
    if set(groups) != expected:
        raise ValueError("incomplete or unexpected experiment grid")
    if any(set(rows) != set(manifest["seeds"]) for rows in groups.values()):
        raise ValueError("missing seed in plot input")
    summary_keys = [tuple(group[k] for k in ("topology", "memory", "p", "arm", "service_mode"))
                    for group in report["summaries"]]
    if len(summary_keys) != len(expected) or set(summary_keys) != expected:
        raise ValueError("summary grid disagrees with observations")
    return directory, manifest, observations, report, groups


def tables(report, groups):
    summary_rows, pair_rows = [], []
    for group in report["summaries"]:
        dimensions = {key: group[key] for key in ("topology", "memory", "p", "arm", "service_mode")}
        counts = {key: group[key] for key in ("zero_service_runs", "absorbing_runs", "native_accounting_discrepancy_slots")}
        for metric, value in group.items():
            if isinstance(value, dict) and "mean" in value:
                summary_rows.append({**dimensions, "metric": metric, **value, **counts})
        key = tuple(dimensions.values())
        seed_rows = list(groups[key].values())
        for pair_summary in group["per_pair"]:
            pair = tuple(pair_summary["pair"])
            if pair not in PAIRS:
                raise ValueError("unexpected demand class")
            pair_dimensions = {**dimensions, "pair": f"{pair[0]}-{pair[1]}", "nominal_rate": PAIRS[pair]}
            pair_count = {"zero_service_runs": pair_summary["zero_service_runs"]}
            for metric, value in pair_summary.items():
                if isinstance(value, dict) and "mean" in value:
                    pair_rows.append({**pair_dimensions, "metric": metric, **value, **pair_count})
            per_seed = []
            for row in seed_rows:
                matching = [item for item in row["per_pair"] if tuple(item["pair"]) == pair]
                if len(matching) != 1:
                    raise ValueError("missing or duplicated per-pair observation")
                item = matching[0]
                if not 0 <= item["pending"] <= item["offered_total"]:
                    raise ValueError("invalid full-horizon request cohort")
                per_seed.append(item)
            derived = {
                "late_throughput_relative_to_nominal_rate": [item["throughput"]/PAIRS[pair] for item in per_seed],
                "cohort_completion_fraction_full_horizon": [
                    (item["offered_total"]-item["pending"])/item["offered_total"]
                    if item["offered_total"] else None for item in per_seed],
            }
            for metric, values in derived.items():
                pair_rows.append({**pair_dimensions, "metric": metric, **interval(values), **pair_count})
    return summary_rows, pair_rows


def save_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def errors(items):
    return [[0 if item["low"] is None else item["mean"]-item["low"] for item in items],
            [0 if item["high"] is None else item["high"]-item["mean"] for item in items]]


def style(ax, axis="x"):
    ax.set_axisbelow(True)
    ax.grid(axis=axis, color="#e2e8f0", linewidth=.65)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=9)


def export(directory):
    directory, manifest, observations, report, groups = load_inputs(directory)
    output = directory / "figures"
    output.mkdir(exist_ok=False)
    summary_rows, pair_rows = tables(report, groups)
    save_csv(output / "summary.csv", summary_rows)
    save_csv(output / "per_pair_summary.csv", pair_rows)
    selected = {(g["memory"], g["p"], g["arm"]): g for g in report["summaries"]
                if g["service_mode"] == "concurrent_per_pair"}
    horizon, warmup, n = manifest["horizon"], manifest["warmup"], len(manifest["seeds"])
    caption = f"Diamond · {n} seeds · bounded H={horizon} · measurement ({warmup}, {horizon}] · pointwise 95% t intervals across seeds"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "savefig.facecolor": "white"})

    fig, axes = plt.subplots(2, 2, figsize=(13.8, 9.8), sharex=True)
    upper = max(1.0, max(g["throughput"]["high"] or g["throughput"]["mean"] for g in selected.values())*1.11)
    for ax, (memory, p) in zip(axes.flat, CONDITIONS):
        items = [selected[memory, p, arm]["throughput"] for arm in ARMS]
        means = [item["mean"] for item in items]
        ax.barh(range(len(ARMS)), means, color=COLORS, xerr=errors(items), height=.62,
                error_kw={"capsize": 3, "elinewidth": 1, "ecolor": "#17202a"})
        ax.axvline(sum(PAIRS.values()), color="#7c8797", linestyle="--", linewidth=1)
        ax.set_yticks(range(len(ARMS)), LABELS)
        ax.invert_yaxis()
        ax.set_xlim(-.025, upper)
        ax.set_title(f"Memory {memory} per node · link success p={p:g}", loc="left", fontsize=12, fontweight="bold")
        ax.set_xlabel("Useful completions / time unit")
        for index, item in enumerate(items):
            endpoint = item["high"] if item["high"] is not None else item["mean"]
            ax.text(endpoint+.012, index, f"{item['mean']:.3f}", va="center", fontsize=8)
            if item["mean"] == 0:
                ax.scatter([0], [index], marker="x", color="#b53b36", zorder=5)
        style(ax)
    fig.suptitle("Concurrent-per-pair service: useful completion rates", x=.025, y=.985, ha="left", fontsize=17, fontweight="bold")
    fig.text(.025, .95, caption, fontsize=10, color="#475569")
    fig.text(.025, .026, "Dashed line: total nominal offered rate 0.90. Zero-service runs are retained. Storage and allocation rules differ between systems.", fontsize=9, color="#475569")
    fig.tight_layout(rect=(0, .06, 1, .925), h_pad=2.8, w_pad=2.8)
    for suffix in ("png", "pdf"):
        fig.savefig(output / f"concurrent_throughput.{suffix}", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(4, 3, figsize=(14.2, 13.0), sharex=True)
    for row_index, (memory, p) in enumerate(CONDITIONS):
        for column_index, (pair, rate) in enumerate(PAIRS.items()):
            ax = axes[row_index, column_index]
            items = [next(item["throughput"] for item in selected[memory, p, arm]["per_pair"]
                          if tuple(item["pair"]) == pair) for arm in ARMS]
            ax.bar(range(len(ARMS)), [item["mean"] for item in items], color=COLORS,
                   yerr=errors(items), width=.66, error_kw={"capsize": 2, "elinewidth": 1, "ecolor": "#17202a"})
            ax.axhline(rate, color="#7c8797", linestyle="--", linewidth=1)
            ax.set_xticks(range(len(ARMS)), SHORT_LABELS, rotation=42, ha="right")
            if row_index == 0:
                ax.set_title(f"Pair {pair[0]}–{pair[1]} · nominal rate {rate:g}", loc="left", fontsize=12, fontweight="bold")
            if column_index == 0:
                ax.set_ylabel(f"Memory {memory} · p={p:g}\nCompletions / time unit", fontsize=10)
            all_items = [next(item["throughput"] for item in group["per_pair"] if tuple(item["pair"]) == pair)
                         for group in selected.values()]
            high = max(rate, max(item["high"] or item["mean"] for item in all_items))
            low = min(0, min(item["low"] or 0 for item in all_items))
            ax.set_ylim(low-.045*high, high*1.16)
            for index, item in enumerate(items):
                if item["mean"] == 0:
                    ax.scatter([index], [0], marker="x", color="#b53b36", zorder=5, s=28)
                    ax.text(index, .035*high, "0", ha="center", fontsize=8, color="#92352e")
            style(ax, "y")
    fig.suptitle("Concurrent service by demand pair", x=.04, y=.985, ha="left", fontsize=17, fontweight="bold")
    fig.text(.04, .955, caption, fontsize=10, color="#475569")
    handles = [Patch(color=COLORS[0], label="Q-CAST"), Patch(color=COLORS[1], label="B: balancing"),
               Patch(color=COLORS[2], label="P: pressure_relaxed"),
               Line2D([0], [0], color="#7c8797", linestyle="--", label="Nominal pair rate"),
               Line2D([0], [0], color="#b53b36", marker="x", linestyle="none", label="Zero mean service")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .035), ncol=5, frameon=False, fontsize=9)
    fig.text(.04, .018, "Bars measure late throughput. CSVs separately report throughput / nominal rate and full-horizon completed / offered request fractions.", fontsize=9, color="#475569")
    fig.tight_layout(rect=(.015, .09, 1, .935), h_pad=1.3, w_pad=1.4)
    for suffix in ("png", "pdf"):
        fig.savefig(output / f"concurrent_per_pair_throughput.{suffix}", dpi=180)
    plt.close(fig)

    notes = {"input_status": manifest["status"], "horizon": horizon, "warmup": warmup, "seeds": manifest["seeds"],
             "figures_service_mode": "concurrent_per_pair", "csv_service_modes": ["fifo", "concurrent_per_pair"],
             "intervals": "Pointwise 95% Student t intervals across seed observations; undefined entries retained with n and undefined counts.",
             "late_throughput_relative_to_nominal_rate": "Per-seed useful completions in (warmup,H] / (H-warmup) / nominal pair arrival rate; not a completion fraction.",
             "cohort_completion_fraction_full_horizon": "Per-seed (offered_total - pending_at_H) / offered_total for all arrivals in [0,H), including final-slot arrivals; undefined if offered_total=0.",
             "input_hashes": {name: digest(directory / name) for name in ("manifest.json", "observations.json", "report.json")},
             "script_sha256": digest(__file__),
             "artifact_hashes": {path.name: digest(path) for path in sorted(output.iterdir()) if path.is_file()}}
    (output / "figure-manifest.json").write_text(json.dumps(notes, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary_rows": len(summary_rows), "per_pair_rows": len(pair_rows)}, indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    export(parser.parse_args().directory)

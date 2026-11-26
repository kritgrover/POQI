"""Verify recovery seed records and recalculate the reported paired comparisons."""

import argparse
from collections import defaultdict
from functools import lru_cache
import gzip
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import statistics

from scipy.stats import t


KEY = ("network", "memory", "policy", "admission", "arm", "seed")
UNCHANGED = ("satisfaction", "minimum_satisfaction", "starved_fraction", "jain_fairness",
             "outage_fraction", "longest_interruption", "any_pair_longest_interruption",
             "zero_service", "final_backlog", "satisfaction_by_hops")


def key(row):
    return tuple(row[field] for field in KEY)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_records(path):
    reader = gzip.open if path.suffix == ".gz" else open
    with reader(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def compare_cell(rows, network, memory):
    selected = [r for r in rows if r["network"] == network and r["memory"] == memory
                and r["policy"] == "pressure_oriented" and r["admission"] == "reserved"]
    by_arm = {arm: {r["seed"]: r for r in selected if r["arm"] == arm} for arm in ("none", "drop0")}
    original, recovery = by_arm["none"], by_arm["drop0"]
    require(original.keys() == recovery.keys(), f"Unmatched seeds on {network}")
    diff = [r["satisfaction"] - original[s]["satisfaction"] for s, r in recovery.items()]
    mean = statistics.fmean(diff)
    half = t.ppf(0.975, len(diff) - 1) * statistics.stdev(diff) / math.sqrt(len(diff))
    costs = [r["stuck_drops"] / r["completed_requests"] for r in recovery.values()]
    return {"network": network, "memory": memory, "seeds": sorted(original),
            "paired_satisfaction_gain": mean, "pointwise_95_t": [mean - half, mean + half],
            "mean_drops_per_completion": statistics.fmean(costs)}


@lru_cache
def critical_value(n):
    return t.ppf(0.975, n - 1)


def check_summary(summary, rows):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)[:-1]].append(row)
    checked = set()
    for cell in summary:
        ident = tuple(cell[k] for k in KEY[:-1])
        seeds = groups[ident]
        require(ident not in checked and len(seeds) == cell["seeds"], f"Wrong seed count {ident}")
        checked.add(ident)
        require(cell["zero_service_runs"] == sum(r["completed_requests"] == 0 for r in seeds),
                f"Wrong zero-service count {ident}")
        for metric, saved in cell.items():
            if not isinstance(saved, list):
                continue
            values = [r[metric] for r in seeds if r[metric] is not None]
            mean = statistics.mean(values) if values else None
            expected = [mean, None, None]
            if len(values) > 1:
                half = critical_value(len(values)) * statistics.stdev(values) / math.sqrt(len(values))
                expected = [mean, mean - half, mean + half]
            for a, b in zip(saved, expected, strict=True):
                require(a is b or (a is not None and b is not None and math.isclose(a, b, abs_tol=1e-12)),
                        f"Summary interval mismatch for {metric}, {ident}")
    require(checked == groups.keys(), "Missing cell summaries")


def check_cohort(directory, legacy=None):
    manifest = read_records(directory / "manifest.json")
    for filename, digest in manifest["file_sha256"].items():
        require(hashlib.sha256((directory / filename).read_bytes()).hexdigest() == digest,
                f"Checksum mismatch in {filename}")
    records = read_records(directory / ("runs.json.gz" if manifest["gzip"] else "runs.json"))
    expected = set(product(*(manifest[name] for name in
                             ("networks", "memory", "policies", "admissions", "arms", "seeds"))))
    require({key(r) for r in records} == expected and len(records) == len(expected) == manifest["runs"],
            f"Missing or duplicate trajectories in {directory}")
    for row in records:
        ident = key(row)
        complete = row["completed_requests"]
        require(complete == sum(pair["completed_requests"] for pair in row["by_pair"]),
                f"Completion mismatch {ident}")
        require(row["starved_fraction"] == sum(pair["starved"] for pair in row["by_pair"]) / len(row["by_pair"]),
                f"Starvation mismatch {ident}")
        require(row["offered_generation"] == row["admitted_generation"] + row["admission_rejections"],
                f"Generation accounting mismatch {ident}")
        for count, ratio in (("stuck_drops", "drops_per_completion"), ("swaps", "swaps_per_completion"),
                             ("expired_pairs", "expired_per_completion")):
            require(row[ratio] == (row[count] / complete if complete else None),
                    f"Interval cost mismatch for {ratio}, {ident}")
    check_summary(read_records(directory / ("summary.json.gz" if manifest["gzip"] else "summary.json")), records)
    if legacy is not None:
        archived = {key(r): r for r in read_records(legacy / directory.name / "runs.json")}
        require(archived.keys() == expected, f"Legacy trajectory set mismatch in {directory}")
        for row in records:
            for field in UNCHANGED:
                require(archived[key(row)][field] == row[field],
                        f"Legacy service or continuity mismatch for {field}, {key(row)}")
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("evidence/recovery"))
    parser.add_argument("--legacy", type=Path, help="optionally compare service/fairness with original local runs")
    args = parser.parse_args()
    rows = [r for name in ("reserved", "tail-drop") for r in check_cohort(args.directory / name, args.legacy)]
    shared = [r for r in rows if r["admission"] == "tail_drop" and r["arm"] == "drop0"]
    starvation = {}
    for policy in sorted({r["policy"] for r in shared}):
        group = [r for r in shared if r["policy"] == policy]
        starvation[policy] = {"trajectories": len(group),
                              "runs_with_a_starved_pair": sum(r["starved_fraction"] > 0 for r in group)}
    print(json.dumps({
        "trajectories_checked": len(rows), "legacy_comparison": args.legacy is not None,
        "two_slot_cycles": [compare_cell(rows, name, 2) for name in ("cycle8", "cycle12")],
        "shared_pool_immediate_recovery": starvation,
    }, indent=2))


if __name__ == "__main__":
    main()

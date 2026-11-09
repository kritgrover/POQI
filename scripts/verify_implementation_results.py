"""Validate saved comparison records and print statistics; never run simulations."""

import argparse
import itertools
import json
import math
from pathlib import Path
from statistics import mean, stdev

from scipy.stats import t


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "SeQUeNCe/example/path_oblivious_corrected/results"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def interval(values):
    if any(value is None for value in values):
        return {"mean": None, "ci95": None}
    center = mean(values)
    half = float(t.ppf(0.975, len(values) - 1)) * stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    return {"mean": center, "ci95": [center - half, center + half] if half is not None else None}


def validate_record(row, tape, horizon):
    d, q = row["distillation_pairs"], row["total_pairs_consumed"]
    require(row["steps"] == row["horizon"] == tape["horizon"] == horizon, "horizon mismatch")
    require(row["finished"] is True and row["stop_reason"] == "fixed_horizon", "unfinished run")
    require(row["status"] == ("completed_horizon" if row["minimum_completed_met"] else "insufficient_completions"),
            "run status mismatch")
    for key in ("initial_inventory", "total_generated", "total_swaps", "total_pairs_consumed", "remaining_inventory"):
        require(type(row[key]) is int and row[key] >= 0, f"invalid count: {key}")
    require(row["initial_inventory"] == sum(edge[2] for edge in tape["edges"]), "initial inventory mismatch")
    events = tape.get("events", [])
    require(len(tape["generations"]) == horizon, "generation tape length mismatch")
    require(not events or len(events) == len(tape["generations"]), "event/generation tape length mismatch")
    require(all(event in ("generate", "swap") for event in events), "invalid finite event")
    generated = sum(batch for step, (_, batch) in enumerate(tape["generations"])
                    if not events or events[step] == "generate")
    require(row["total_generated"] == generated, "generation tape mismatch")
    require(sum(row["completed_hops"].values()) == sum(pair[2] for pair in row["completed_by_pair"]) == q,
            "completion histogram mismatch")
    require(all(type(pair[2]) is int and pair[2] >= 0 for pair in row["final_inventory"]), "invalid final inventory")
    require(sum(pair[2] for pair in row["final_inventory"]) == row["remaining_inventory"], "final inventory sum mismatch")
    require(row["remaining_inventory"] == row["initial_inventory"] + row["total_generated"]
            - (2 * d - 1) * row["total_swaps"] - d * q, "inventory conservation mismatch")
    hops = {int(h): count for h, count in row["completed_hops"].items()}
    require(all(h >= 1 and type(count) is int and count >= 0 for h, count in hops.items()), "invalid hop histogram")
    longest = max(hops, default=1)
    corrected, legacy = [0] * (longest + 1), [0] * max(longest, 2)
    legacy[1] = d
    for h in range(2, longest + 1):
        corrected[h] = d * (1 + corrected[h // 2] + corrected[(h + 1) // 2])
    for n in range(2, len(legacy)):
        legacy[n] = d * (legacy[n // 2] + legacy[(n + 1) // 2])
    for name, costs, shift in (("corrected", corrected, 0), ("legacy", legacy, 1)):
        denominator = sum(costs[h - shift] * count for h, count in hops.items())
        require(row[f"{name}_denominator"] == denominator, f"{name} denominator mismatch")
        value = row[f"{name}_overhead"]
        require(value is None if denominator == 0 else value is not None and
                math.isclose(value, row["total_swaps"] / denominator, rel_tol=1e-12, abs_tol=1e-12),
                f"{name} overhead mismatch (zero denominator must be null)")


def verify_directory(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "completed", f"{directory}: incomplete manifest")
    reps, ds = manifest["replicates"], manifest["distillation_pairs"]
    require(type(reps) is int and reps > 0, "invalid replicate count")
    require(ds and all(type(d) is int and d > 0 for d in ds) and len(set(ds)) == len(ds), "invalid D values")
    expected = set(itertools.product(range(reps), ds, ("original", "corrected")))
    records, tapes = {}, {}
    for path in sorted((directory / "runs").glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            key = (row["replicate"], row["distillation_pairs"], row["dynamics"])
            require(key in expected and key not in records, "unexpected or duplicate run")
            input_id = f"input-{row['replicate']:03d}"
            require(row["input_id"] == input_id, "paired input ID mismatch")
            if input_id not in tapes:
                tapes[input_id] = json.loads((directory / "inputs" / f"{input_id}.json").read_text(encoding="utf-8"))
            validate_record(row, tapes[input_id], manifest["horizon"])
            records[key] = row
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ValueError(f"{path}: {error}") from error
    require(set(records) == expected, f"{directory}: missing runs/partners: {sorted(expected - set(records))}")
    results = {}
    if 1 in ds:
        for metric in ("total_pairs_consumed", "legacy_overhead", "corrected_overhead"):
            original = [records[i, 1, "original"][metric] for i in range(reps)]
            corrected = [records[i, 1, "corrected"][metric] for i in range(reps)]
            a, b = interval(original), interval(corrected)
            delta = [None if x is None or y is None else y - x for x, y in zip(original, corrected)]
            results[metric] = {"released": a, "corrected": b, "paired_difference": interval(delta),
                               "relative_change_percent": 100 * (b["mean"] / a["mean"] - 1)
                               if a["mean"] not in (None, 0) and b["mean"] is not None else None}
    return {"directory": str(directory), "validated_runs": len(records), "master_seed": manifest["seed"],
            "replicates": reps, "horizon": manifest["horizon"], "D1": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="*", help="comparison output directories")
    args = parser.parse_args()
    try:
        groups = [verify_directory(path) for path in (args.directories or [DEFAULT / "cycle", DEFAULT / "grid"])]
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    print(json.dumps({"validated_runs": sum(group["validated_runs"] for group in groups), "groups": groups},
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

"""Replay the concurrent two-qubit lossy diamond with reversed native demand order."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

try:
    from . import qcast_concurrent as concurrent
    from . import qcast_concurrent_audit as audit
except ImportError:
    import qcast_concurrent as concurrent
    import qcast_concurrent_audit as audit

pilot = concurrent.pilot
ROOT = pilot.ROOT
SEEDS = tuple(range(7271, 7281))
HORIZON, WARMUP = 400, 100
ORDERS = ("sorted", "reversed")
PAIRS = sorted(pilot.specification("diamond")[3])
METRICS = ("throughput", "completed", "mean_backlog", "final_backlog", "attempts", "swaps")
PAIR_METRICS = ("throughput", "completed", "final_backlog")


class OrderedBridge:
    """Change only the ordering of pending pairs in the native SLOT call."""

    def __init__(self, bridge, order):
        if order not in ORDERS:
            raise ValueError("unknown demand order")
        self.bridge, self.order = bridge, order

    def initialize(self, config):
        return self.bridge.initialize(config)

    def slot(self, pairs, outcomes):
        audit.require(pairs == sorted(set(pairs)), "runner changed the canonical pending list")
        submitted = pairs[::-1] if self.order == "reversed" else pairs
        response = self.bridge.slot(submitted, outcomes)
        audit.require([tuple(item["pair"]) for item in response["delivered"]] == submitted,
                      "native response order differs from submitted demands")
        return response


def replay(data, order):
    """Check native submission order, then replay physical ebits and service."""
    audit.require(order in ORDERS, "unknown demand order")
    slots = []
    for row in data["slots"]:
        native = row["native"]
        delivered = native["delivered"]
        pairs = [tuple(item["pair"]) for item in delivered]
        audit.require(pairs == sorted(set(pairs), reverse=order == "reversed"), "incorrect submission order")
        audit.require(native["author_counts"] == [item["author_count"] for item in delivered],
                      "native author counts do not match delivery records")
        # The archived checker expects the active-set listing in ascending order.
        # Canonicalize only that presentation for its queue membership comparison.
        canonical = sorted(delivered, key=lambda item: item["pair"])
        slots.append({**row, "native": {**native, "delivered": canonical,
                                        "author_counts": [item["author_count"] for item in canonical]}})
    return audit.replay({**data, "slots": slots})


def allocation_counts(slots):
    """Count first major-path awards for each unordered active demand set."""
    counts = Counter()
    for row in slots:
        native = row["native"]
        active = tuple(sorted(tuple(item["pair"]) for item in native["delivered"]))
        paths = native["major_paths"]
        first = None
        if paths:
            nodes = paths[0]["nodes"]
            first = tuple(sorted((nodes[0], nodes[-1])))
            audit.require(first in active, "major path has no matching active demand")
        counts[active, first] += 1
    return counts


def allocation_rows(counts):
    return [{"active": [list(p) for p in active], "first_major_pair": list(first) if first else None,
             "slots": count} for (active, first), count in sorted(counts.items(),
                                                                 key=lambda item: (item[0][0], item[0][1] or ()))]


def metrics(sorted_rows, reversed_rows, fields):
    return {name: {"sorted": pilot.interval([row[name] for row in sorted_rows]),
                   "reversed": pilot.interval([row[name] for row in reversed_rows]),
                   "paired_reversed_minus_sorted": pilot.interval([b[name]-a[name] for a, b in zip(sorted_rows, reversed_rows)])}
            for name in fields}


def summarize(observations):
    groups = {order: {row["seed"]: row for row in observations if row["order"] == order} for order in ORDERS}
    audit.require(len(observations) == 2*len(SEEDS) and all(set(group) == set(SEEDS) for group in groups.values()),
                  "missing, duplicate or unexpected seed/order")
    original, changed = [[groups[order][seed] for seed in SEEDS] for order in ORDERS]
    for a, b in zip(original, changed):
        audit.require(all(a[field] == b[field] for field in ("workload_sha256", "potential_sha256")),
                      "unmatched physical opportunities or requests")
    by_pair = []
    for pair in PAIRS:
        a, b = [[next(item for item in row["per_pair"] if tuple(item["pair"]) == pair) for row in rows]
                for rows in (original, changed)]
        by_pair.append({"pair": list(pair), **metrics(a, b, PAIR_METRICS),
                        "completions_total": {order: sum(item["completed"] for item in rows)
                                              for order, rows in zip(ORDERS, (a, b))},
                        "zero_service_seeds": {order: [seed for seed, item in zip(SEEDS, rows) if not item["completed"]]
                                               for order, rows in zip(ORDERS, (a, b))}})
    return {"metrics": metrics(original, changed, METRICS), "by_pair": by_pair}


def run_suite(output, main_directory, build):
    output, main_directory, build = (Path(p).resolve() for p in (output, main_directory, build))
    audit.require(output.is_relative_to(ROOT/"results") and output != ROOT/"results",
                  "output must be a new directory below results/")
    source = main_directory/"manifest.json"
    historical = json.loads(source.read_text(encoding="utf-8"))
    audit.require(historical["status"] == "passed" and historical["author_revision"] == pilot.REVISION
                  and historical["seeds"] == list(SEEDS) and historical["horizon"] == HORIZON
                  and historical["warmup"] == WARMUP, "wrong historical reference")
    runtime = concurrent.verify_build(build)
    audit.require(runtime == historical["native_inputs"], "native build differs from historical run")
    references = {row["seed"]: row for row in historical["runs"]
                  if (row["topology"], row["memory"], row["p"], row["arm"], row["service_mode"])
                  == ("diamond", 2, .5, "QCAST-Slot", "concurrent_per_pair")}
    audit.require(set(references) == set(SEEDS), "missing historical references")
    sources = [Path(__file__).resolve(), Path(concurrent.__file__), Path(audit.__file__),
               audit.PHYSICAL_AUDIT, Path(pilot.__file__), pilot.BRIDGE]
    output.mkdir(parents=True, exist_ok=False)
    (output/"runs").mkdir()
    manifest = {"status": "running", "scope": "Post-hoc paired order sensitivity on original seeds",
                "topology": "diamond", "memory": 2, "p": .5, "q": 1, "D": 1,
                "service_mode": "concurrent_per_pair", "orders": list(ORDERS), "seeds": list(SEEDS),
                "horizon": HORIZON, "warmup": WARMUP, "author_revision": pilot.REVISION,
                "build": str(build), "native_inputs": runtime, "reference": str(main_directory),
                "reference_manifest_sha256": pilot.sha256(source),
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "source_sha256": {p.relative_to(ROOT).as_posix(): pilot.sha256(p) for p in sources},
                "runs": []}
    pilot.write_json(output/"manifest.json", manifest)
    observations, allocations = [], defaultdict(Counter)
    try:
        with pilot.NativeBridge(build, output/"bridge-stderr.log") as bridge:
            for seed in SEEDS:
                ref = references[seed]
                path = main_directory/ref["artifact"]
                audit.require(pilot.sha256(path) == ref["sha256"], "reference trajectory hash mismatch")
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    archived = json.load(stream)
                for order in ORDERS:
                    record = concurrent.run_trajectory("diamond", 2, .5, seed, "QCAST-Slot", HORIZON,
                                                       OrderedBridge(bridge, order), "concurrent_per_pair")
                    if order == "sorted":
                        audit.require(record == archived, f"baseline differs from archived trajectory, seed {seed}")
                    audit.require(all(record[k] == archived[k] for k in ("requests", "channels", "potential_sha256", "workload_sha256")),
                                  "original requests or physical opportunities changed")
                    count = replay(record, order)
                    observed = concurrent.observe(record, WARMUP)
                    audit.close(audit.observation(record, WARMUP), observed, "independent observation")
                    allocation = allocation_counts(record["slots"][WARMUP:])
                    allocations[order].update(allocation)
                    observations.append({**observed, "order": order, "allocations": allocation_rows(allocation)})
                    name = f"runs/{order}-{seed}.json.gz"
                    with gzip.open(output/name, "wt", encoding="utf-8", compresslevel=1) as stream:
                        json.dump({**record, "order": order}, stream, separators=(",", ":"), allow_nan=False)
                    manifest["runs"].append({"seed": seed, "order": order, "artifact": name, "sha256": pilot.sha256(output/name),
                                             "reference_sha256": ref["sha256"], "completed_full_horizon": count,
                                             "exact_baseline_replay": order == "sorted"})
                pilot.write_json(output/"manifest.json", manifest)
                print(f"Replayed both orders for seed {seed}", flush=True)
        report = summarize(observations)
        report["allocations"] = {order: allocation_rows(allocations[order]) for order in ORDERS}
        pilot.write_json(output/"observations.json", observations)
        pilot.write_json(output/"report.json", report)
        manifest["artifact_sha256"] = {name: pilot.sha256(output/name) for name in ("observations.json", "report.json", "bridge-stderr.log")}
        manifest["status"] = "passed"
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        pilot.write_json(output/"manifest.json", manifest)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--main", type=Path, default=ROOT/"results/qcast/concurrent-main-01")
    parser.add_argument("--build", type=Path, default=ROOT/"results/qcast/pilot-smoke-01/build")
    args = parser.parse_args()
    run_suite(args.output, args.main, args.build)

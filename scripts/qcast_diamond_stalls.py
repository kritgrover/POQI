"""Certify absorbing inventories in the two-qubit persistent-pressure diamond.

The certificate depends on the support of future demand, the no-expiry storage
rule, and reserved admission. Link outcomes and future request order are free.
The historical independent physical replay checks reachability from empty.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

if __package__:
    from . import qcast_concurrent_audit as physical_audit
else:
    import qcast_concurrent_audit as physical_audit


EDGES = ((0, 1), (0, 2), (1, 3), (2, 3))
DEMAND = frozenset(((0, 1), (0, 3), (1, 2)))
CONDITION = {"topology": "diamond", "memory": 2, "arm": "POQI-Persistent-pressure_relaxed",
             "service_mode": "concurrent_per_pair"}


def certificate(inventory, demand=DEMAND):
    """Return a sufficient no-transition witness or None for a replayed snapshot."""
    partners = defaultdict(set)
    origin_use = Counter()
    occupancy = Counter()
    stored = Counter()
    for item in inventory:
        u, v = item["endpoints"]
        if item["deadline_tick"] is not None or (u, v) in demand:
            return None
        stored[u, v] += 1
        partners[u].add(v)
        partners[v].add(u)
        occupancy.update((u, v))
        origin_use.update((o["node"], o["neighbor"]) for o in item["origins"])

    if any(len(neighbors) > 1 for neighbors in partners.values()):
        return None  # Two distinct partners may enable a swap.

    blocked = []
    for u, v in EDGES:
        full = [n for n in (u, v) if occupancy[n] == 2]
        # Two slots and two physical neighbors give each generation origin one slot.
        reserved = [n for n, neighbor in ((u, v), (v, u)) if origin_use[n, neighbor] == 1]
        if not full and not reserved:
            return None  # A trial on this edge could be selected first.
        blocked.append({"edge": [u, v], "full_endpoints": full, "quota_full_endpoints": reserved})
    return {"stored": [{"endpoints": list(edge), "count": n} for edge, n in sorted(stored.items())],
            "occupancy": [occupancy[n] for n in range(4)], "blocked_edges": blocked}


def analyze_trajectory(data, warmup):
    if any(data[k] != v for k, v in CONDITION.items()):
        raise ValueError("requires a two-qubit, concurrent, no-expiry pressure diamond")
    if not 0 <= warmup < data["horizon"]:
        raise ValueError("invalid measurement window")
    physical_audit.replay(data)
    first_tick = witness = frozen_inventory = None
    attempts = swaps = 0
    for row in data["slots"]:
        inventory = row["final_inventory"]
        if len(inventory) != row["remaining_pairs"]:
            raise ValueError("final snapshot cardinality disagrees with pair conservation")
        if first_tick is None:
            witness = certificate(inventory)
            if witness is not None:
                first_tick = row["start"] + 1
                frozen_inventory = inventory
        elif (inventory != frozen_inventory or row["selected"] or row["swaps"] or
              row["start_completed"] or row["end_completed"] or row["expired_pairs"] or row["discarded_pairs"]):
            raise ValueError("observed transition after certified boundary")
        if row["start"] >= warmup:
            attempts += len(row["selected"])
            swaps += row["swaps"]
    completions = sum(warmup < item["time"] <= data["horizon"] for item in data["completions"])
    return {"seed": data["seed"], "p": data["p"], "first_certified_end_tick": first_tick,
            "witness": witness, "subsequent_slots_checked": data["horizon"] - first_tick if first_tick else 0,
            "measured_attempts": attempts, "measured_swaps": swaps, "measured_completions": completions}


def analyze(directory):
    directory = Path(directory)
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["status"] != "passed":
        raise ValueError("requires a completed source experiment")
    seeds = manifest["seeds"]
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("expected distinct experiment seeds")
    expected = {(p, seed) for seed in seeds for p in (0.5, 1.0)}
    rows = []
    seen = set()
    for record in manifest["runs"]:
        if any(record[k] != v for k, v in CONDITION.items()):
            continue
        key = record["p"], record["seed"]
        if key not in expected or key in seen:
            raise ValueError("unexpected or duplicate target trajectory")
        seen.add(key)
        compressed = (directory / record["artifact"]).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != record["sha256"]:
            raise ValueError(f"raw input hash mismatch: {record['artifact']}")
        data = json.loads(gzip.decompress(compressed))
        if (data["p"], data["seed"]) != key or data["horizon"] != manifest["horizon"]:
            raise ValueError("trajectory identity disagrees with manifest")
        rows.append({**analyze_trajectory(data, manifest["warmup"]),
                     "artifact": record["artifact"], "sha256": record["sha256"]})
    if seen != expected:
        raise ValueError("missing target trajectory")
    groups = []
    for p in (0.5, 1.0):
        group = [row for row in rows if row["p"] == p]
        groups.append({"p": p, "runs": len(group),
                       "certified": sum(row["witness"] is not None for row in group),
                       "zero_measured_service": sum(row["measured_completions"] == 0 for row in group)})
    return {"source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "source_code_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in (Path(__file__), Path(physical_audit.__file__), physical_audit.PHYSICAL_AUDIT)},
            "condition": CONDITION, "possible_demand_pairs": [list(p) for p in sorted(DEMAND)],
            "horizon": manifest["horizon"], "warmup": manifest["warmup"],
            "groups": groups, "trajectories": sorted(rows, key=lambda r: (r["p"], r["seed"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="historical concurrent run directory")
    parser.add_argument("--output", type=Path, help="new JSON file (default: stdout)")
    args = parser.parse_args()
    report = json.dumps(analyze(args.directory), indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(report, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(report)


if __name__ == "__main__":
    main()

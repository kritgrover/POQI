"""Run the fixed, paired, slotted experiment described in Matched_Protocol.md."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
import gzip
import hashlib
from itertools import combinations, product
import json
from pathlib import Path
import platform
import random

from scripts.srs_protocol import SlottedProtocol


ROOT = Path(__file__).resolve().parents[1]
SEEDS = tuple(range(12101, 12113))
HORIZON = 2000
WARMUP = 500
TAU = 50
ARMS = (
    ("srs25", "srs", 0.25), ("srs50", "srs", 0.5), ("srs100", "srs", 1.0),
    ("pressure", "pressure_oriented", 1.0), ("pre_drop", "pressure_pre_drop", 1.0),
    ("post_drop", "pressure_post_drop", 1.0),
)


@dataclass(frozen=True)
class Scenario:
    nodes: int = 8
    slots: int = 2
    lifetime: int = 10
    background: float = 0.0
    generation: float = 0.5
    swap_success: float = 1.0
    load: float = 0.1

    @property
    def name(self):
        return (f"n{self.nodes}-m{self.slots}-t{self.lifetime}-bg{self.background:g}"
                f"-p{self.generation:g}-s{self.swap_success:g}-load{self.load:g}")


def design():
    cells = [Scenario(*args) for args in product((8, 12), (2, 4), (10, 30), (0.0, 0.02))]
    for background in (0.0, 0.02):
        base = Scenario(background=background)
        cells.extend(replace(base, **changes) for changes in (
            {"generation": 1.0}, {"swap_success": 0.8}, {"lifetime": 100}, {"load": 0.35}))
    return cells


def workload(cell, seed, horizon):
    n = cell.nodes
    distances = {(u, v): min(v - u, n - v + u) for u, v in combinations(range(n), 2)}
    eligible = [pair for pair, distance in distances.items() if distance >= 2]
    core = set(random.Random(7919 * seed + 13).sample(eligible, round(0.12 * len(distances))))
    hop_budget = cell.load * n * cell.generation
    core_rate = hop_budget / sum(distances[pair] for pair in core)
    bg_rate = cell.background * hop_budget / sum(d for pair, d in distances.items() if pair not in core)
    rates = {pair: core_rate if pair in core else bg_rate for pair in distances if pair in core or bg_rate}
    arrivals = [[] for _ in range(horizon)]
    by_pair = {pair: [] for pair in rates}
    for (u, v), rate in rates.items():
        rng = random.Random(f"srs-requests/{n}/{u}/{v}/{seed}")
        moment = rng.expovariate(rate)
        while moment < horizon:
            tick = int(moment)
            arrivals[tick].append((moment, (u, v)))
            by_pair[u, v].append(tick)
            moment += rng.expovariate(rate)
    edges = tuple(pair for pair, distance in distances.items() if distance == 1)
    order_rng = random.Random(f"srs-edge-order/{n}/{seed}")
    outcomes_rng = random.Random(f"srs-link-success/{n}/{seed}")
    clocks = []
    digest = hashlib.sha256()
    for events in arrivals:
        potential = {edge: outcomes_rng.random() < cell.generation for edge in edges}
        order = list(edges)
        order_rng.shuffle(order)
        links = {edge: potential[edge] for edge in order}
        requests = tuple(pair for _, pair in sorted(events))
        clocks.append((links, requests))
        digest.update(json.dumps([list(links.items()), requests], separators=(",", ":")).encode())
        digest.update(b"\n")
    return edges, core, rates, by_pair, clocks, digest.hexdigest()


def pair_outcomes(arrivals, departures, warmup, horizon, followup):
    """FIFO interval and fixed-follow-up accounting from integer slot timestamps."""
    if len(departures) > len(arrivals):
        raise AssertionError("more departures than requests")
    intervals = []
    restricted = []
    previous = 0
    for arrival, finish in zip(arrivals, departures):
        if finish < arrival or finish < previous or finish >= horizon:
            raise AssertionError("invalid completion time")
        gap = finish - max(arrival, previous, warmup)
        if gap > 0:
            intervals.append(gap)
        previous = finish
        if warmup <= arrival <= horizon - followup:
            restricted.append(min(finish - arrival, followup))
    remaining = arrivals[len(departures):]
    trailing = 0
    if remaining:
        trailing = horizon - max(previous, remaining[0], warmup)
        if trailing:
            intervals.append(trailing)
        restricted.extend(followup for t in remaining if warmup <= t <= horizon - followup)
    return {
        "offered": sum(t >= warmup for t in arrivals),
        "completed": sum(t >= warmup for t in departures),
        "end_backlog": len(remaining),
        "unfinished_window_arrivals": sum(t >= warmup for t in remaining),
        "restricted_wait_sum": sum(restricted), "restricted_wait_count": len(restricted),
        "intervals": intervals, "right_censored_length": trailing,
    }


def sum_classes(pairs, length):
    totals = {key: sum(row[key] for row in pairs) for key in (
        "offered", "completed", "end_backlog", "unfinished_window_arrivals",
        "restricted_wait_sum", "restricted_wait_count")}
    nominal = length * sum(row["rate"] for row in pairs)
    intervals = sorted(t for row in pairs for t in row["intervals"])
    service = [row["completed"] / (length * row["rate"]) for row in pairs]
    totals.update(
        class_count=len(pairs),
        nominal_offered=nominal,
        satisfaction=totals["completed"] / nominal if nominal else None,
        minimum_satisfaction=min(service, default=None),
        jain=sum(service)**2 / (len(service) * sum(s*s for s in service)) if any(service) else None,
        restricted_wait=totals["restricted_wait_sum"] / totals["restricted_wait_count"]
                        if totals["restricted_wait_count"] else None,
        longest_gap=max(intervals, default=0),
        gap_p95=intervals[(95 * len(intervals) + 99) // 100 - 1] if intervals else None,
        outage_share=sum(t for t in intervals if t >= TAU) / (len(pairs) * length) if pairs else None,
        starved_classes=sum(r["completed"] == 0 and bool(r["intervals"]) for r in pairs),
        unfinished_fraction=totals["unfinished_window_arrivals"] / totals["offered"] if totals["offered"] else None,
    )
    return totals


def run_block(task):
    cell, seed = task
    edges, core, rates, by_pair, clocks, fingerprint = workload(cell, seed, HORIZON)
    rows = []
    for arm, policy, swap_attempt in ARMS:
        engine = SlottedProtocol(edges, cell.slots, policy=policy, seed=seed,
                                 cutoff=cell.lifetime, max_length=cell.nodes - 1,
                                 swap_success=cell.swap_success, swap_attempt=swap_attempt)
        finishes = defaultdict(list)
        start_counts = Counter()
        for tick, (links, requests) in enumerate(clocks):
            if tick == WARMUP:
                start_counts = engine.counters.copy()
            for pair, arrived in engine.step(tick, links, requests):
                if arrived != by_pair[pair][len(finishes[pair])]:
                    raise AssertionError("service disagrees with FIFO arrival history")
                finishes[pair].append(tick)
        counts = {key: n - start_counts[key] for key, n in engine.counters.items()}
        pair_rows = []
        for pair, rate in rates.items():
            pair_rows.append({"pair": pair, "core": pair in core, "rate": rate,
                              **pair_outcomes(by_pair[pair], finishes[pair], WARMUP, HORIZON, TAU)})
        if sum(r["end_backlog"] for r in pair_rows) != engine.pending:
            raise AssertionError("unmatched pending request")
        total_completed = sum(row["completed"] for row in pair_rows)
        if counts.get("offered_generation", 0) != len(edges) * (HORIZON - WARMUP):
            raise AssertionError("physical opportunity count disagrees with the design")
        rows.append({"cell": cell.name, "seed": seed, "arm": arm, "input_sha256": fingerprint,
                     "counts": counts, "total_completed": total_completed,
                     "drops_per_completion": counts.get("dropped", 0) / total_completed if total_completed else None,
                     "core": sum_classes([r for r in pair_rows if r["core"]], HORIZON-WARMUP),
                     "background": sum_classes([r for r in pair_rows if not r["core"]], HORIZON-WARMUP),
                     "pairs": pair_rows})
    if cell.generation == 1:
        before, after = rows[-2:]
        if before["pairs"] != after["pairs"] or before["counts"] != after["counts"]:
            raise AssertionError("pre- and post-success recovery must coincide on lossless links")
    return rows


def source_digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output directory")
    args.output.mkdir(parents=True)
    tasks = list(product(design(), SEEDS))
    sources = ["Matched_Protocol.md", "scripts/matched_srs.py", "scripts/srs_protocol.py",
               "src/poqi/simulation/inventory.py", "src/poqi/simulation/sequence_adapter.py"]
    fingerprints = {p: source_digest(ROOT/p) for p in sources}
    partial = args.output / "runs.partial"
    with partial.open("wb") as target, gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as compressed:
        with ProcessPoolExecutor(args.workers) as pool:
            for index, rows in enumerate(pool.map(run_block, tasks), 1):
                for row in rows:
                    compressed.write((json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode())
                if index % 24 == 0:
                    print(f"{index}/{len(tasks)} paired blocks", flush=True)
    if fingerprints != {p: source_digest(ROOT/p) for p in sources}:
        raise RuntimeError("an experiment input changed during execution")
    partial.rename(args.output / "runs.jsonl.gz")
    manifest = {"protocol": "Matched_Protocol.md", "source_sha256_lf": fingerprints,
                "cells": {c.name: asdict(c) for c in design()}, "seeds": SEEDS,
                "arms": ARMS, "slots": HORIZON, "measure_from": WARMUP, "followup_slots": TAU,
                "rows": len(tasks)*len(ARMS), "python": platform.python_version()}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

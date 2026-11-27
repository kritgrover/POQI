"""Post hoc checks of the lossless reversal in the matched SRS experiment.

Run python -m scripts.matched_lossless_diagnostic --output <new directory>.
Lossless generation at load .05 gives exactly the primary .5-generation/.10-
load request times. Lossless load .10 reproduces the published sensitivity.
In two additional arms each slot permutes the pressure pivot visitation order
using a dedicated random stream. All settling passes in that slot follow that
order. A pivot has only two qubits and therefore at most one pair of swap
inputs. Permuting its partner scan cannot change which candidate it selects.
Physical reservations, endpoint label order, and the entire external schedule
are unchanged. In particular the reference SRS coin stream is independent of
these permutations. The diagnostic addresses synchronous deterministic sweeps.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import random

from scripts.matched_srs import (HORIZON, ROOT, SEEDS, TAU, WARMUP, Scenario,
                                 pair_outcomes, source_digest, sum_classes, workload)
from scripts.matched_srs_report import estimate, write_table
from scripts.srs_protocol import SlottedProtocol


ARMS = (
    ("srs50", "srs", False),
    ("pressure", "pressure_oriented", False),
    ("pre_drop", "pressure_pre_drop", False),
    ("pressure_shuffle", "pressure_oriented", True),
    ("pre_drop_shuffle", "pressure_pre_drop", True),
)
METRICS = ("satisfaction", "restricted_wait", "outage_share", "end_backlog")


def summarize_arm(cell, seed, arm, policy, shuffled, edges, rates, by_pair, clocks):
    engine = SlottedProtocol(edges, cell.slots, policy=policy, seed=seed,
                             cutoff=cell.lifetime, max_length=cell.nodes-1,
                             swap_attempt=.5 if policy == "srs" else 1.)
    pivot_rng = random.Random(f"lossless-pivot-order/{cell.nodes}/{seed}")
    finishes = defaultdict(list)
    start_counts = Counter()
    for tick, (opportunities, requests) in enumerate(clocks):
        if tick == WARMUP:
            start_counts = engine.counters.copy()
        if shuffled:
            # Inventory.order fixes pair labels and reservations. Only the
            # iterable used for visits changes. M=2 excludes partner-choice ties.
            order = list(range(cell.nodes))
            pivot_rng.shuffle(order)
            engine.backend.inventory.nodes = tuple(order)
        for pair, arrival in engine.step(tick, opportunities, requests):
            assert by_pair[pair][len(finishes[pair])] == arrival
            finishes[pair].append(tick)
    outcomes = [dict(rate=rate, **pair_outcomes(by_pair[pair], finishes[pair], WARMUP, HORIZON, TAU))
                for pair, rate in rates.items()]
    summary = sum_classes(outcomes, HORIZON-WARMUP)
    assert summary["end_backlog"] == engine.pending
    return {"arm": arm, "seed": seed, "load": cell.load, "generation": cell.generation,
            **{key: summary[key] for key in (*METRICS, "completed", "offered", "nominal_offered")},
            **{key: engine.counters[key]-start_counts[key]
               for key in ("attempts", "admitted", "swaps", "dropped")}}


def run_seed(seed):
    reference = workload(Scenario(), seed, HORIZON)
    rows, fingerprints = [], []
    for load in (.05, .10):
        cell = Scenario(generation=1., load=load)
        edges, core, rates, by_pair, clocks, digest = workload(cell, seed, HORIZON)
        assert edges == reference[0] and core == reference[1]
        assert all(list(lossless.keys()) == list(primary.keys()) and all(lossless.values())
                   for (lossless, _), (primary, _) in zip(clocks, reference[4]))
        if load == .05:
            assert rates == reference[2] and by_pair == reference[3]
            assert all(requests == original for (_, requests), (_, original) in zip(clocks, reference[4]))
        fingerprints.append({"seed": seed, "load": load, "input_sha256": digest,
                             "primary_input_sha256": reference[5]})
        rows.extend(summarize_arm(cell, seed, *arm, edges, rates, by_pair, clocks) for arm in ARMS)
    return rows, fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output directory")
    files = ["scripts/matched_lossless_diagnostic.py", "scripts/matched_srs.py",
             "scripts/matched_srs_report.py", "scripts/srs_protocol.py",
             "src/poqi/simulation/sequence_adapter.py", "src/poqi/simulation/inventory.py",
             "Matched_Protocol.md"]
    fingerprints = {p: source_digest(ROOT/p) for p in files}
    archive = ROOT/"evidence/matched/runs.jsonl.gz"
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    original = {}
    conditions = {Scenario().name: "primary", Scenario(generation=1.).name: "original_lossless"}
    with gzip.open(archive, "rt", encoding="utf-8") as inp:
        for line in inp:
            row = json.loads(line)
            if row["cell"] in conditions:
                original[conditions[row["cell"]], row["seed"], row["arm"]] = row
    rows, schedules = [], []
    with ProcessPoolExecutor(args.workers) as pool:
        for results, clocks in pool.map(run_seed, SEEDS):
            rows.extend(results)
            schedules.extend(clocks)
    index = {(r["load"], r["seed"], r["arm"]): r for r in rows}
    for s in schedules:
        assert s["primary_input_sha256"] == original["primary", s["seed"], "srs50"]["input_sha256"]
        if s["load"] == .10:
            assert s["input_sha256"] == original["original_lossless", s["seed"], "srs50"]["input_sha256"]
    for seed in SEEDS:
        for arm in ("srs50", "pressure", "pre_drop"):
            known = original["original_lossless", seed, arm]
            observed = index[.10, seed, arm]
            assert all(observed[k] == known["core"][k] for k in (*METRICS, "offered", "completed"))
            assert all(observed[k] == known["counts"].get(k, 0) for k in ("attempts","admitted","swaps","dropped"))
    def series(generation, load, arm, metric):
        if generation == .5:
            return [original["primary", s, arm]["core"][metric] for s in SEEDS]
        return [index[load, s, arm][metric] for s in SEEDS]
    summaries = [{"generation": 1., "load": load, "arm": arm, "metric": metric,
                  **estimate(series(1., load, arm, metric))}
                 for load in (.05, .10) for arm, _, _ in ARMS for metric in METRICS]
    contrasts = []
    def compare(label, left, right):
        for metric in METRICS:
            delta = [a-b for a, b in zip(series(*left, metric), series(*right, metric))]
            contrasts.append({"contrast": label, "metric": metric, "positive_seeds": sum(v > 0 for v in delta),
                              **estimate(delta)})
    for load in (.05, .10):
        for arm, other in (("pre_drop", "srs50"), ("pre_drop_shuffle", "srs50"),
                           ("pressure_shuffle", "pressure"), ("pre_drop_shuffle", "pre_drop"),
                           ("pre_drop_shuffle", "pressure_shuffle")):
            compare(f"lossless_load{load:g}_{arm}_minus_{other}", (1., load, arm), (1., load, other))
    for arm in ("srs50", "pressure", "pre_drop"):
        compare(f"equal_absolute_requests_lossless_minus_primary_{arm}", (1., .05, arm), (.5, .10, arm))
        compare(f"lossless_load0.1_minus_load0.05_{arm}", (1., .10, arm), (1., .05, arm))
    assert fingerprints == {p: source_digest(ROOT/p) for p in files}
    args.output.mkdir(parents=True)
    write_table(args.output/"seeds.csv", rows)
    write_table(args.output/"summaries.csv", summaries)
    write_table(args.output/"paired.csv", contrasts)
    manifest = {"purpose": "Post hoc: disentangle absolute demand intensity and pivot order in the lossless reversal.",
                "nodes": 8, "slots": 2, "cutoff": 10, "max_segments": 7, "generation": 1, "swap_success": 1,
                "core_loads": [.05, .10], "background": 0, "arms": ARMS, "seeds": SEEDS,
                "horizon": HORIZON, "warmup": WARMUP, "followup": TAU, "rows": len(rows),
                "original_archive_sha256": archive_hash, "source_sha256_lf": fingerprints, "inputs": schedules,
                "estimate": "Seed-paired differences. Intervals are pointwise two-sided 95% Student-t intervals.",
                "pivot_order": "Separate per-seed RNG chooses one new permutation per slot, shared by both shuffled arms and both loads. Only visitation changes at two slots."}
    (args.output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(f"Verified {len(rows)} diagnostic trajectories across {len(SEEDS)} seeds.")


if __name__ == "__main__":
    main()

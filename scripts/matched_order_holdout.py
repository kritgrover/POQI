"""Freeze then run the single held-out test of pressure pivot order.

Run python -m scripts.matched_order_holdout freeze followed by
python -m scripts.matched_order_holdout run. Supply --output to use a new
directory when reproducing the recorded inputs and the deterministic experiment.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.matched_lossless_diagnostic import summarize_arm
from scripts.matched_srs import HORIZON, ROOT, WARMUP, Scenario, source_digest, workload
from scripts.matched_srs_report import estimate, write_table


SEEDS = tuple(range(13101, 13113))
ARMS = (("pre_drop", "pressure_pre_drop", False),
        ("pre_drop_shuffle", "pressure_pre_drop", True), ("srs50", "srs", False))
SOURCES = (
    "scripts/matched_order_holdout.py", "scripts/matched_lossless_diagnostic.py",
    "scripts/matched_srs.py", "scripts/matched_srs_report.py", "scripts/srs_protocol.py",
    "src/poqi/simulation/sequence_adapter.py", "src/poqi/simulation/inventory.py",
    "Matched_Protocol.md", "evidence/matched-lossless/manifest.json",
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def specification():
    return {
        "question": "Does randomizing the pressure pivot visit order improve core service on fresh seeds?",
        "prediction": "Pre-attempt eviction with a new random pivot permutation each slot has higher mean core satisfaction than the same policy with fixed pivot order.",
        "primary_contrast": "shuffled pre-attempt eviction minus fixed pre-attempt eviction",
        "primary_endpoint": "Core completions in the window divided by nominal core arrivals in that window.",
        "analysis": "Mean within-seed difference, two-sided pointwise 95% Student-t interval across 12 seeds. The prediction is supported if the lower endpoint exceeds zero. SRS50 contrasts are descriptive.",
        "design": "Fresh seeds 13101-13112 on an 8-node cycle, two reserved slots per node, lifetime 10, maximum 7 elementary links per stored pair. Unit generation and swap success, no background demand, normalized core load 0.05. No tuning or further sweeps.",
        "matching": "Same sparse core demand and ordered link opportunity sequence across arms; request traces equal the primary absolute load at p_gen=.5 and normalized load .10 for the same seed.",
        "seeds": list(SEEDS), "arms": list(map(list, ARMS)), "horizon": HORIZON, "warmup": WARMUP,
        "prior_seeds": list(range(12101, 12113)),
        "source_sha256_lf": {p: source_digest(ROOT/p) for p in SOURCES},
    }


def run_seed(seed):
    cell = Scenario(generation=1., load=.05)
    edges, core, rates, by_pair, clocks, digest = workload(cell, seed, HORIZON)
    matched = workload(Scenario(), seed, HORIZON)
    assert edges == matched[0] and core == matched[1] and rates == matched[2] and by_pair == matched[3]
    assert all(tuple(e) == tuple(other) and requests == original
               for (e, requests), (other, original) in zip(clocks, matched[4]))
    return [dict(**summarize_arm(cell, seed, *arm, edges, rates, by_pair, clocks),
                 input_sha256=digest) for arm in ARMS]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "run"))
    parser.add_argument("--output", type=Path, default=ROOT/"evidence/matched-lossless/holdout")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    protocol = args.output/"protocol.json"
    if args.stage == "freeze":
        args.output.mkdir(parents=True, exist_ok=False)
        protocol.write_text(json.dumps(dict(frozen_utc=timestamp(), **specification()), indent=2)+"\n",
                            encoding="utf-8")
        print(f"Frozen protocol SHA-256 {hashlib.sha256(protocol.read_bytes()).hexdigest()}")
        return
    if {path.name for path in args.output.iterdir()} != {"protocol.json"}:
        parser.error("run requires the frozen protocol in a directory without results")
    frozen = json.loads(protocol.read_text(encoding="utf-8"))
    frozen.pop("frozen_utc")
    if frozen != specification() or set(SEEDS) & set(frozen["prior_seeds"]):
        raise RuntimeError("the design, sources, or disjoint-seed requirement changed after freezing")
    started = timestamp()
    rows = []
    with ProcessPoolExecutor(args.workers) as pool:
        for block in pool.map(run_seed, SEEDS):
            rows.extend(block)
    if frozen != specification():
        raise RuntimeError("a source changed during execution")
    index = {(r["arm"], r["seed"]): r for r in rows}
    contrasts = []
    for left, right in (("pre_drop_shuffle", "pre_drop"), ("pre_drop_shuffle", "srs50"), ("pre_drop", "srs50")):
        vals = [index[left, s]["satisfaction"]-index[right, s]["satisfaction"] for s in SEEDS]
        contrasts.append({"left": left, "right": right, "metric": "core.satisfaction",
                          "primary": right == "pre_drop", "positive_seeds": sum(v > 0 for v in vals),
                          **estimate(vals)})
    write_table(args.output/"seeds.csv", rows)
    write_table(args.output/"paired.csv", contrasts)
    manifest = {"started_utc": started, "completed_utc": timestamp(), "trajectories": len(rows),
                "sha256": {f: hashlib.sha256((args.output/f).read_bytes()).hexdigest()
                           for f in ("protocol.json", "seeds.csv", "paired.csv")}}
    (args.output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(contrasts[0], indent=2))


if __name__ == "__main__":
    main()

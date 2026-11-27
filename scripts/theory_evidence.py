"""Rebuild the tandem rate comparisons and public, uncapped freeze certificates."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform

import networkx as nx

from poqi.simulation import run_simulation
from scripts.chain_tandem_check import ample_endpoint_checks
from scripts.dead_state_search import Arm, TOPOLOGIES, frozen_generation_words


ROOT = Path(__file__).resolve().parents[1]


def replay(graph, demand, slots, policy, events):
    trace = [{"kind": kind, "endpoints": pair, "time": i}
             for i, (kind, pair) in enumerate(events, 1)]
    return run_simulation(graph, dict.fromkeys(demand, 1.0), memory_slots=slots,
                          swap_policy=policy, admission_policy="reserved", service_order="per_pair",
                          horizon=len(trace) + 2, ticks_per_time_unit=1, trace=trace).to_dict()


def certify(topology, policy, count):
    edges, demand = TOPOLOGIES[topology]
    arm = Arm(edges, demand, 2, policy)
    nx.set_edge_attributes(arm.graph, 1.0, "generation_capacity")
    certificates = []
    for word in frozen_generation_words(arm, count):
        start = replay(arm.graph, demand, 2, policy, word)
        live = start["live_pairs"]
        if not live or any(tuple(item["endpoints"]) in demand for item in live):
            raise AssertionError("public replay failed to reach a demand-incompatible inventory")
        checks = 0
        for backlog in (0, 7):
            # Exercise the actual request queues above the search's cutoff.
            prefix = word + [("request", pair) for pair in demand for _ in range(backlog)]
            base = replay(arm.graph, demand, 2, policy, prefix)
            if base["live_pairs"] != live or base["completed_requests"] != 0:
                raise AssertionError("requests changed the alleged terminal inventory")
            if any(row["unserved_requests"] != backlog for row in base["service_by_pair"]):
                raise AssertionError("uncapped backlog differs from the witness setup")
            for event in arm.events():
                after = replay(arm.graph, demand, 2, policy, prefix + [event])
                if (after["live_pairs"] != live or after["completed_requests"] != 0
                        or after["admitted_generation"] != base["admitted_generation"]
                        or after["swaps"] != base["swaps"]):
                    raise AssertionError(f"public event {event} escaped the candidate freeze")
                if after["offered_generation"] - base["offered_generation"] != (event[0] == "generate"):
                    raise AssertionError("public simulator did not process the generation")
                for row in after["service_by_pair"]:
                    arrivals = event == ("request", tuple(row["endpoints"]))
                    if row["unserved_requests"] != backlog + arrivals:
                        raise AssertionError("public simulator did not retain the expected request")
                checks += 1
        inventory = [{"endpoints": item["endpoints"], "origins": item["origins"]} for item in live]
        release_types = sorted({tuple(item["endpoints"]) for item in live})
        for pair in release_types:
            # The prefix has no requests; including this extra class leaves
            # the demand-blind generation and swapping trajectory unchanged.
            result = replay(arm.graph, (*demand, pair), 2, policy, word + [("request", pair)])
            if result["completed_requests"] != 1 or result["live_pairs"] == live:
                raise AssertionError(f"background request for {pair} did not release memory")
        certificates.append({"topology": topology, "policy": policy, "slots_per_node": 2,
                             "edges": edges, "demand": demand, "generation_word": [pair for _, pair in word],
                             "frozen_inventory": inventory, "backlogs_per_class_checked": [0, 7],
                             "public_next_events_checked": checks, "verified_background_release_types": release_types})
    return certificates


def run(output):
    rates = ample_endpoint_checks()
    cases = (("chain", "pressure_relaxed", 2), ("diamond", "pressure_relaxed", 2),
             ("diamond", "pressure_oriented", 2), ("cycle5", "pressure_relaxed", 1),
             ("cycle5", "pressure_oriented", 1), ("cycle6", "pressure_relaxed", 1),
             ("cycle6", "pressure_oriented", 1))
    witnesses = [witness for topology, policy, count in cases for witness in certify(topology, policy, count)]
    files = {"tandem.json": rates, "uncapped-freezes.json": witnesses}
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in files.items():
        (output / name).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
    inputs = ["scripts/theory_evidence.py", "scripts/chain_tandem_check.py", "scripts/dead_state_search.py",
              "src/poqi/simulation/inventory.py", "src/poqi/simulation/sequence_adapter.py"]
    manifest = {
        "command": "python -B -m scripts.theory_evidence --output evidence/theory",
        "freeze_time_model": "distinct deterministic event times, no expiry, no recovery, unit swap success",
        "tandem_model": "independent Poisson generators, permanent backlog, unit swap success, no expiry",
        "initial_state": "empty inventory and empty unbounded per-demand queues in the freeze replays",
        "python": platform.python_version(),
        "libraries": {name: version(name) for name in ("networkx", "numpy", "sequence")},
        "source_sha256_lf": {name: lf_digest(ROOT / name) for name in inputs},
        "artifact_sha256_lf": {name: lf_digest(output / name) for name in files},
        "tandem_comparisons": len(rates), "distinct_topology_policy_traces": len(witnesses),
        "next_event_checks": sum(w["public_next_events_checked"] for w in witnesses),
        "background_release_checks": sum(len(w["verified_background_release_types"]) for w in witnesses),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Verified {len(rates)} rate comparisons, {len(witnesses)} freeze traces and "
          f"{manifest['next_event_checks']} uncapped next events.")


def lf_digest(path):
    """SHA-256 of text after normalizing Git's CRLF working-tree conversion."""
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)

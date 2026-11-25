import gzip
import hashlib
import json
from copy import deepcopy

import pytest

from scripts import qcast_concurrent, qcast_diamond_stalls as stalls


@pytest.fixture
def frozen():
    # Two 02 pairs have distinct physical origins, one of them created by swaps.
    return [
        {"endpoints": [0, 2], "deadline_tick": None,
         "origins": [{"node": 0, "neighbor": 1}, {"node": 2, "neighbor": 3}]},
        {"endpoints": [0, 2], "deadline_tick": None,
         "origins": [{"node": 0, "neighbor": 2}, {"node": 2, "neighbor": 0}]},
        {"endpoints": [1, 3], "deadline_tick": None,
         "origins": [{"node": 1, "neighbor": 3}, {"node": 3, "neighbor": 1}]},
    ]


def test_full_endpoints_and_nonfull_edge_with_exhausted_reservations(frozen):
    witness = stalls.certificate(frozen)
    assert witness["occupancy"] == [2, 1, 2, 1]
    assert witness["stored"] == [{"endpoints": [0, 2], "count": 2}, {"endpoints": [1, 3], "count": 1}]
    assert {"edge": [1, 3], "full_endpoints": [], "quota_full_endpoints": [1, 3]} in witness["blocked_edges"]
    assert len(witness["blocked_edges"]) == 4


def test_reservation_depends_on_generation_origin_after_swapping(frozen):
    frozen[-1]["origins"] = [{"node": 1, "neighbor": 0}, {"node": 3, "neighbor": 2}]
    assert stalls.certificate(frozen) is None  # A new physical 13 now fits at both ends.


def test_possible_future_demand_disqualifies_idle_inventory(frozen):
    assert stalls.certificate(frozen, stalls.DEMAND | {(0, 2)}) is None


def test_expiry_distinct_partners_and_empty_inventory(frozen):
    frozen[0]["deadline_tick"] = 11
    assert stalls.certificate(frozen) is None
    frozen[0]["deadline_tick"] = None
    # Physical links 02,13,23; nodes 2 and 3 now have two partners.
    frozen[0] = {"endpoints": [2, 3], "deadline_tick": None,
                 "origins": [{"node": 2, "neighbor": 3}, {"node": 3, "neighbor": 2}]}
    assert stalls.certificate(frozen) is None
    assert stalls.certificate([]) is None


@pytest.fixture(scope="module")
def records():
    return {p: qcast_concurrent.run_trajectory("diamond", 2, p, 7274, stalls.CONDITION["arm"], 40, None)
            for p in (0.5, 1.0)}


def test_replay_certifies_first_end_boundary_including_transition_into_trap(records):
    result = stalls.analyze_trajectory(records[0.5], warmup=10)
    assert result["first_certified_end_tick"] == 2
    assert result["subsequent_slots_checked"] == 38
    assert result["measured_attempts"] == result["measured_swaps"] == result["measured_completions"] == 0


def test_zero_completions_do_not_prove_a_permanent_stall():
    # No completions in this very short run, but further transitions are possible.
    data = qcast_concurrent.run_trajectory("diamond", 2, 1., 7274, stalls.CONDITION["arm"], 1, None)
    result = stalls.analyze_trajectory(data, warmup=0)
    assert result["measured_completions"] == 0
    assert result["witness"] is None
    assert result["first_certified_end_tick"] is None


@pytest.mark.parametrize(("field", "invalid"), [("memory", 4), ("arm", "POQI-Cutoff10-pressure_relaxed"),
                                               ("service_mode", "fifo"), ("topology", "chain")])
def test_other_physics_are_outside_the_certificate_scope(records, field, invalid):
    with pytest.raises(ValueError, match="requires a two-qubit"):
        stalls.analyze_trajectory({**records[0.5], field: invalid}, 10)


def test_corrupt_snapshot_is_rejected_even_if_repeated_id_has_identical_fields(records):
    data = deepcopy(records[0.5])
    data["slots"][-1]["final_inventory"].append(data["slots"][-1]["final_inventory"][0])
    with pytest.raises((ValueError, AssertionError)):
        stalls.analyze_trajectory(data, 10)


def test_manifest_includes_both_controls_and_verifies_raw_bytes(tmp_path, records):
    manifest = {"status": "passed", "seeds": [7274], "horizon": 40, "warmup": 10, "runs": []}
    for p, record in records.items():
        compressed = gzip.compress(json.dumps(record).encode())
        name = f"p{p}.json.gz"
        (tmp_path / name).write_bytes(compressed)
        manifest["runs"].append({**stalls.CONDITION, "p": p, "seed": 7274, "artifact": name,
                                 "sha256": hashlib.sha256(compressed).hexdigest()})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    groups = stalls.analyze(tmp_path)["groups"]
    assert [item["certified"] for item in groups] == [1, 0]
    control = manifest["runs"].pop()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="missing target"):
        stalls.analyze(tmp_path)
    manifest["runs"].extend([control, control])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate target"):
        stalls.analyze(tmp_path)
    manifest["runs"].pop()
    path.write_text(json.dumps(manifest))
    (tmp_path / control["artifact"]).write_bytes(b"corrupted raw file")
    with pytest.raises(ValueError, match="raw input hash mismatch"):
        stalls.analyze(tmp_path)

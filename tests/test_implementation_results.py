"""The saved-result verifier must reject corrupt or incomplete evidence."""

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "implementation_result_verifier", Path(__file__).resolve().parents[1] / "scripts/verify_implementation_results.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def saved_results(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "inputs").mkdir()
    manifest = {"status": "completed", "replicates": 2, "distillation_pairs": [1], "horizon": 10, "seed": 271}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # One directly consumed pair needs zero swaps, so overhead is undefined.
    for replicate in range(2):
        tape = {"horizon": 10, "edges": [[0, 1, 20]], "generations": [[0, 1]] + [[0, 0]] * 9}
        (tmp_path / "inputs" / f"input-{replicate:03d}.json").write_text(json.dumps(tape), encoding="utf-8")
        for dynamics in ("original", "corrected"):
            row = {"replicate": replicate, "distillation_pairs": 1, "dynamics": dynamics,
                   "input_id": f"input-{replicate:03d}", "steps": 10, "horizon": 10, "finished": True,
                   "status": "completed_horizon", "minimum_completed_met": True,
                   "stop_reason": "fixed_horizon", "initial_inventory": 20, "total_generated": 1,
                   "total_swaps": 0, "total_pairs_consumed": 1, "remaining_inventory": 20,
                   "completed_hops": {"1": 1}, "completed_by_pair": [[0, 1, 1]], "final_inventory": [[0, 1, 20]],
                   "corrected_denominator": 0, "legacy_denominator": 0,
                   "corrected_overhead": None, "legacy_overhead": None}
            (tmp_path / "runs" / f"r{replicate:03d}-d1-{dynamics}.json").write_text(json.dumps(row), encoding="utf-8")
    return tmp_path


def test_valid_direct_completion_keeps_undefined_overhead(saved_results):
    result = verifier.verify_directory(saved_results)
    assert result["validated_runs"] == 4
    assert result["D1"]["total_pairs_consumed"]["paired_difference"] == {"mean": 0, "ci95": [0, 0]}
    assert result["D1"]["corrected_overhead"]["corrected"] == {"mean": None, "ci95": None}
    assert result["D1"]["corrected_overhead"]["relative_change_percent"] is None


@pytest.mark.parametrize("field,value,message", [
    ("total_generated", 2, "generation tape mismatch"),
    ("total_swaps", 1, "inventory conservation mismatch"),
    ("corrected_denominator", 1, "corrected denominator mismatch"),
    ("corrected_overhead", 0, "zero denominator must be null"),
    ("input_id", "input-001", "paired input ID mismatch"),
    ("status", "failed", "run status mismatch"),
])
def test_corrupt_record_fails_with_filename(saved_results, field, value, message):
    path = saved_results / "runs/r000-d1-corrected.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row[field] = value
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match=f"r000-d1-corrected.json.*{message}"):
        verifier.verify_directory(saved_results)


def test_missing_partner_is_not_silently_dropped(saved_results):
    (saved_results / "runs/r000-d1-original.json").unlink()
    with pytest.raises(ValueError, match="missing runs/partners"):
        verifier.verify_directory(saved_results)


def test_finite_event_tape_counts_only_generation_events(saved_results):
    for path in (saved_results / "inputs").glob("*.json"):
        tape = json.loads(path.read_text(encoding="utf-8"))
        tape.update(generations=[[0, 1]] + [[0, 99]] * 9, events=["generate"] + ["swap"] * 9)
        path.write_text(json.dumps(tape), encoding="utf-8")
    assert verifier.verify_directory(saved_results)["validated_runs"] == 4


def test_insufficient_completions_remain_valid_evidence(saved_results):
    for path in (saved_results / "runs").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        row.update(status="insufficient_completions", minimum_completed_met=False)
        path.write_text(json.dumps(row), encoding="utf-8")
    assert verifier.verify_directory(saved_results)["validated_runs"] == 4

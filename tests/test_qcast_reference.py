"""Small analytic controls and audits of explicitly supplied native JVM results.

Set QCAST_VALIDATION_DIR to a completed qcast_reference.py output to exercise
native-artifact tests. Absence skips those tests visibly; it never fabricates
reference results or downloads/builds software during the ordinary root suite.
"""

from copy import deepcopy
import json
import math
import os
from pathlib import Path

import pytest

from scripts import qcast_reference as reference


@pytest.mark.parametrize("ps,width,q,expected", [
    ([0.3], 3, 0, 0.9),          # direct pairs do not require a swap
    ([1, 1, 1], 2, 0.5, 0.5), # two internal swaps per lane
    ([0.5, 0.5], 2, 0.8, 0.5),
    ([0.2, 0.7], 1, 0.9, 0.126),
    ([0, 1], 2, 1, 0),
    ([1, 1], 3, 0, 0),
])
def test_exhaustive_metric_matches_hand_calculations(ps, width, q, expected):
    assert reference.expected_yield(ps, width, q) == pytest.approx(expected)


@pytest.mark.parametrize("ps,width,q", [
    ([], 1, 1), ([1] * 7, 1, 1), ([1], 0, 1), ([1], 9, 1),
    ([1], True, 1), ([1], 1.5, 1), ([math.nan], 1, 1),
    ([math.inf], 1, 1), ([-0.1], 1, 1), ([1.1], 1, 1),
    ([1], 1, -1), ([True], 1, 1),
])
def test_metric_oracle_rejects_invalid_or_unbounded_cases(ps, width, q):
    with pytest.raises(ValueError):
        reference.expected_yield(ps, width, q)


@pytest.fixture(scope="module")
def native_bundle():
    directory = os.environ.get("QCAST_VALIDATION_DIR")
    if not directory:
        pytest.skip("QCAST_VALIDATION_DIR not set: native Q-CAST run not available")
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "passed"
    assert manifest["author_revision"] == reference.REVISION
    assert manifest["driver_sha256"] == reference.sha256(reference.DRIVER)
    assert manifest["runner_sha256"] == reference.sha256(reference.__file__)
    for name, expected in manifest["artifact_hashes"].items():
        assert reference.sha256(directory / name) == expected, name
    for name, expected in manifest["source_hashes"].items():
        assert reference.sha256(directory / "build" / name) == expected, name
    report = json.loads((directory / "reference.json").read_text(encoding="utf-8"))
    audit = json.loads((directory / "audit.json").read_text(encoding="utf-8"))
    return report, audit


def test_executed_native_reference_passes_independent_audit(native_bundle):
    report, saved_audit = native_bundle
    assert reference.audit_report(report) == saved_audit
    assert saved_audit["controlled_cases"] == 16
    assert saved_audit["path_allocations_checked"] == 17
    assert saved_audit["metric_queries_checked"] == 2


def test_native_work_retains_zero_service_and_detects_duplicate_accounting(native_bundle):
    native = native_bundle[0]["native_work"]
    assert native["seeded_p_half_slots"] == [
        [1, 1], [1, 2], [1, 1], [0, 0], [1, 1], [1, 1], [1, 1], [1, 1]]
    assert native["duplicate_pair_diagnostic"]["physical_ebits"] == 2
    assert native["duplicate_pair_diagnostic"]["reported_ebits"] == 4
    assert native["duplicate_pair_diagnostic"]["reported_pair_entries_served"] == 2


def test_width_priority_is_not_global_expected_yield_optimization(native_bundle):
    case = next(c for c in native_bundle[0]["controlled_cases"]
                if c["name"] == "widest_first_counterexample")
    choice = case["major_paths"][0]
    assert choice["nodes"] == [0, 1, 2]
    assert choice["width"] == 2
    assert choice["score"] == pytest.approx(0.2)
    assert reference.expected_yield([1], 1, 0.1) == 1


def test_recovery_consumes_extra_opportunities_and_can_still_fail(native_bundle):
    cases = {c["name"]: c for c in native_bundle[0]["controlled_cases"]}
    disabled = cases["recovery_disabled_failure"]
    recovered = cases["recovery_repairs_failed_segment"]
    failed = cases["recovery_detour_failure"]
    assert (disabled["effective_channel_attempts"], disabled["delivered_ebits"]) == (3, 0)
    assert (recovered["effective_channel_attempts"], recovered["delivered_ebits"],
            recovered["swap_attempts"]) == (5, 1, 3)
    assert (failed["effective_channel_attempts"], failed["delivered_ebits"],
            failed["swap_attempts"]) == (5, 0, 1)


@pytest.mark.parametrize("corruption", [
    "revision", "missing_case", "duplicate_case", "memory", "residual_memory",
    "width", "metric", "assigned", "delivery", "physical_reuse", "surplus",
    "reset", "metric_query", "swap_count", "missing_metrics", "swap_flags",
    "internal_connection", "recovery_endpoint", "native_accounting", "native_seed",
])
def test_independent_audit_rejects_corrupted_native_records(native_bundle, corruption):
    report = deepcopy(native_bundle[0])
    case = report["controlled_cases"][1]  # direct width two; two physical lanes
    if corruption == "revision":
        report["source_commit"] = "unknown"
    elif corruption == "missing_case":
        report["controlled_cases"].pop()
    elif corruption == "duplicate_case":
        report["controlled_cases"][-1] = report["controlled_cases"][0]
    elif corruption == "memory":
        case["occupied_qubits_after_P2"][0] += 1
    elif corruption == "residual_memory":
        case["remaining_qubits_after_P2"][0] += 1
    elif corruption == "width":
        case["major_paths"][0]["width"] += 1
    elif corruption == "metric":
        case["major_paths"][0]["score"] += 0.25
    elif corruption == "assigned":
        case["channels"][0]["assigned"] = False
    elif corruption == "delivery":
        case["ebits_per_pair"][0] = 3
    elif corruption == "physical_reuse":
        case["physical_delivery_channels"][0][1] = case["physical_delivery_channels"][0][0]
    elif corruption == "surplus":
        case["surplus_ebits_for_one_request_per_pair"] = 0
    elif corruption == "reset":
        case["reset_clean"] = False
    elif corruption == "metric_query":
        report["metric_queries"][0]["score"] += 0.1
    elif corruption == "swap_count":
        case["successful_swaps"] = 1
    elif corruption == "missing_metrics":
        report["metric_queries"] = []
    elif corruption == "swap_flags":
        case["post_p4_channels"][0]["s1"] = True
    elif corruption == "internal_connection":
        chain = next(c for c in report["controlled_cases"] if c["name"] == "chain_success")
        chain["successful_swap_inputs"] = []
        chain["successful_swaps"] = 0
    elif corruption == "recovery_endpoint":
        recovery = next(c for c in report["controlled_cases"] if c["name"] == "recovery_repairs_failed_segment")
        recovery["recovery_paths"][0]["major"] = [0, 3]
    elif corruption == "native_accounting":
        report["native_work"]["duplicate_pair_diagnostic"]["reported_ebits"] = 2
    elif corruption == "native_seed":
        report["native_work"]["seeded_p_half_slots"][3] = [1, 1]
    with pytest.raises(ValueError):
        reference.audit_report(report)


def test_runner_rejects_output_outside_ignored_results(tmp_path):
    with pytest.raises(ValueError, match="under results"):
        reference.run_reference(tmp_path / "source", tmp_path / "maven", tmp_path / "output")
    assert not (tmp_path / "output").exists()


"""Executed native phase tests for the matched-opportunity Q-CAST bridge.

QCAST_PILOT_BUILD must name an existing build of the pinned sources plus
SlotBridge.kt. Tests never download or build software implicitly. The injected
bits are conditional physical outcomes, not estimates of success probability.
"""

import json
import os
from pathlib import Path

import pytest

from scripts.qcast_pilot import NativeBridge


@pytest.fixture(scope="module")
def native_build():
    configured = os.environ.get("QCAST_PILOT_BUILD")
    if not configured:
        pytest.skip("QCAST_PILOT_BUILD not set: native pilot bridge unavailable")
    build = Path(configured)
    assert (build / "classpath.txt").is_file()
    assert (build / "target/classes/poqi/qcast/SlotBridge.class").is_file()
    return build


@pytest.fixture(scope="module")
def native(native_build, tmp_path_factory):
    with NativeBridge(native_build, tmp_path_factory.mktemp("native-slot") / "stderr.log") as bridge:
        yield bridge


def config(memory, edges, *, q=1, alpha=0, k=0, locations=None):
    if locations is None:
        locations = [(i, 0) for i in range(len(memory))]
    return "\n".join([str(len(memory)), str(alpha), str(q), str(k)] +
                     [f"{m} {x} {y}" for m, (x, y) in zip(memory, locations)] +
                     [f"{u} {v} {lanes}" for u, v, lanes in edges])


def counts(result):
    return {tuple(row["pair"]): row["count"] for row in result["delivered"]}


def check_conservation(result):
    assert result["reset_clean"] is True
    assert set(result["successful"]) <= set(result["assigned"])
    assert sum(result["occupancy"]) == 2 * len(result["assigned"])
    assert result["swaps"] == len(result["successful_swap_inputs"])
    assert sum(int(row["s1"]) + int(row["s2"]) for row in result["post_p4_channels"]) == 2 * result["swaps"]
    assert result["total_remaining_pairs"] == len(result["successful"]) - result["swaps"]
    assert result["total_remaining_pairs"] == sum(row["count"] for row in result["all_pairs"])
    physical_paths = [path for row in result["all_pairs"] for path in row["paths"]]
    physical_channels = [channel for path in physical_paths for channel in path]
    assert len(physical_channels) == len(set(physical_channels))
    assert sorted(physical_channels) == sorted(result["successful"])
    assert all(row["count"] == len(row["paths"]) for row in result["delivered"])


@pytest.mark.parametrize("memory,lanes,bits,attempts,ebits", [
    ([1, 1], 3, [True, True, True], 1, 1),
    ([4, 4], 2, [True, True], 2, 2),
    ([3, 3], 3, [False, True, False], 3, 1),
    ([2, 2], 2, [False, False], 2, 0),
    ([0, 2], 2, [True, True], 0, 0),
])
def test_direct_memory_channels_and_controlled_failures(native, memory, lanes, bits, attempts, ebits):
    ready = native.initialize(config(memory, [(0, 1, lanes)]), recovery=False)
    assert ready["memory"] == memory
    assert ready["q"] == 1
    assert len(ready["channels"]) == lanes
    result = native.slot([(0, 1)], bits)
    assert len(result["assigned"]) == attempts
    assert counts(result) == {(0, 1): ebits}
    assert result["total_remaining_pairs"] == ebits
    assert result["swaps"] == 0
    check_conservation(result)


def test_chain_parallel_width_and_pivot_capacity(native):
    edges = [(0, 1, 2), (1, 2, 2)]
    native.initialize(config([2, 4, 2], edges), recovery=False)
    full = native.slot([(0, 2)], [True] * 4)
    assert full["occupancy"] == [2, 4, 2]
    assert full["major_paths"] == [{"score": 2, "width": 2, "nodes": [0, 1, 2]}]
    assert full["swaps"] == 2
    assert counts(full) == {(0, 2): 2}
    check_conservation(full)
    native.initialize(config([2, 1, 2], edges), recovery=False)
    blocked = native.slot([(0, 2)], [True] * 4)
    assert blocked["assigned"] == []
    assert counts(blocked) == {(0, 2): 0}
    check_conservation(blocked)


def test_nested_demand_author_prefix_count_is_not_a_physical_ebit(native):
    native.initialize(config([1, 2, 1], [(0, 1, 1), (1, 2, 1)]), recovery=False)
    # Equal scores: the earlier end-to-end demand receives the channel path.
    result = native.slot([(0, 2), (0, 1)], [True, True])
    assert result["major_paths"][0]["nodes"] == [0, 1, 2]
    assert counts(result) == {(0, 2): 1, (0, 1): 0}
    assert result["author_counts"] == [1, 1]
    assert result["author_accounting_discrepancy"] is True
    assert result["total_remaining_pairs"] == 1
    check_conservation(result)


def test_competing_diamond_requests_use_disjoint_physical_channels(native):
    edges = [(0, 1, 1), (1, 3, 1), (0, 2, 1), (2, 3, 1)]
    locations = [(0, 0), (1, 0), (0, 1), (1, 1)]
    native.initialize(config([2] * 4, edges, alpha=0.6931471805599453,
                             locations=locations), recovery=False)
    result = native.slot([(0, 1), (0, 3)], [True] * 4)
    assert [row["nodes"] for row in result["major_paths"]] == [[0, 1], [0, 2, 3]]
    assert result["assigned"] == [0, 2, 3]
    assert counts(result) == {(0, 1): 1, (0, 3): 1}
    used = [channel for row in result["delivered"] for path in row["paths"] for channel in path]
    assert len(used) == len(set(used)) == 3
    check_conservation(result)


def test_lossless_diamond_tie_can_allocate_surplus_to_first_demand(native):
    edges = [(0, 1, 1), (1, 3, 1), (0, 2, 1), (2, 3, 1)]
    native.initialize(config([2] * 4, edges), recovery=False)
    result = native.slot([(0, 1), (0, 3)], [True] * 4)
    assert [row["nodes"] for row in result["major_paths"]] == [[0, 1], [0, 2, 3, 1]]
    assert counts(result) == {(0, 1): 2, (0, 3): 0}
    assert result["author_counts"] == [2, 1]
    assert result["author_accounting_discrepancy"] is True
    assert result["assigned"] == [0, 1, 2, 3]
    assert result["swaps"] == 2
    check_conservation(result)


@pytest.mark.parametrize("recovery,bits,attempts,ebits,swaps", [
    (False, [True, False, True, True, True], 3, 0, 0),
    (True, [True, False, True, True, True], 5, 1, 3),
    (True, [True, False, True, False, True], 5, 0, 1),
])
def test_recovery_success_failure_and_resource_cost(native, recovery, bits, attempts, ebits, swaps):
    edges = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (1, 4, 1), (2, 4, 1)]
    locations = [(0, 0), (1, 0), (2, 0), (3, 0), (1.5, 1)]
    native.initialize(config([1, 4, 4, 1, 2], edges, k=1, locations=locations), recovery=recovery)
    result = native.slot([(0, 3)], bits)
    assert result["major_paths"][0]["nodes"] == [0, 1, 2, 3]
    assert len(result["assigned"]) == attempts
    assert counts(result) == {(0, 3): ebits}
    assert result["swaps"] == swaps
    if recovery:
        assert result["recovery_paths"][0]["path"]["nodes"] == [1, 4, 2]
    check_conservation(result)


def test_reset_and_replay_and_unassigned_outcomes_do_not_inform_allocation(native):
    native.initialize(config([1, 1], [(0, 1, 3)], alpha=0.6931471805599453), recovery=False)
    first = native.slot([(0, 1)], [True, False, False])
    unassigned_changed = native.slot([(0, 1)], [True, True, True])
    assert first == unassigned_changed
    failed = native.slot([(0, 1)], [False, True, True])
    assert first["major_paths"] == failed["major_paths"]
    assert first["assigned"] == failed["assigned"] == [0]
    assert counts(failed) == {(0, 1): 0}
    assert native.slot([(0, 1)], [True, False, False]) == first
    empty = native.slot([], [True, True, True])
    assert empty["assigned"] == empty["delivered"] == []
    assert empty["total_remaining_pairs"] == 0
    check_conservation(empty)


def test_q1_phase_replay_matches_validated_reference_cases(native):
    directory = os.environ.get("QCAST_VALIDATION_DIR")
    if not directory:
        pytest.skip("QCAST_VALIDATION_DIR not set: prior native reference replay unavailable")
    reference = json.loads((Path(directory) / "reference.json").read_text(encoding="utf-8"))
    checked = 0
    for case in reference["controlled_cases"]:
        if float(case["topology"].strip().splitlines()[2]) != 1 or case["p4_swap_probability"] != 1:
            continue
        native.initialize(case["topology"], recovery=case["recovery_enabled"])
        result = native.slot(case["requests"], [c["success"] for c in case["channels"]])
        assert [row["count"] for row in result["delivered"]] == case["ebits_per_pair"]
        assert result["major_paths"] == case["major_paths"]
        assert result["occupancy"] == case["occupied_qubits_after_P2"]
        assert result["swaps"] == case["swap_attempts"]
        check_conservation(result)
        checked += 1
    assert checked == 10


@pytest.mark.parametrize("invalid", ["nonunit_swap", "duplicate_demand", "wrong_bit_count"])
def test_invalid_inputs_fail_visibly(native_build, tmp_path, invalid):
    with NativeBridge(native_build, tmp_path / "stderr.log") as bridge:
        with pytest.raises(RuntimeError, match="bridge error"):
            if invalid == "nonunit_swap":
                bridge.initialize(config([1, 1], [(0, 1, 1)], q=0.5))
            else:
                bridge.initialize(config([1, 1], [(0, 1, 1)]))
                if invalid == "duplicate_demand":
                    bridge.slot([(0, 1), (0, 1)], [True])
                else:
                    bridge.slot([(0, 1)], [True, False])
        assert bridge.process.wait(timeout=5) == 2

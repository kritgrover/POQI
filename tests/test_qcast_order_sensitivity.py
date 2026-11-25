import os
from pathlib import Path

import pytest

from scripts import qcast_order_sensitivity as study


def delivered(pairs):
    return [{"pair": list(pair), "author_count": i} for i, pair in enumerate(pairs)]


class RecordingBridge:
    def initialize(self, config):
        self.config = config

    def slot(self, pairs, outcomes):
        self.pairs, self.outcomes = pairs, outcomes
        return {"delivered": delivered(pairs)}


@pytest.mark.parametrize("order", study.ORDERS)
def test_only_native_demand_order_changes(order):
    native = RecordingBridge()
    adapter = study.OrderedBridge(native, order)
    adapter.initialize("topology")
    pairs, outcomes = [(0, 3), (1, 2)], [True, False]
    response = adapter.slot(pairs, outcomes)
    expected = pairs if order == "sorted" else pairs[::-1]
    assert native.config == "topology"
    assert pairs == [(0, 3), (1, 2)]
    assert native.pairs == expected
    assert native.outcomes is outcomes
    assert response["delivered"] == delivered(expected)


def test_rejects_invalid_or_duplicate_submission_order():
    bridge = RecordingBridge()
    with pytest.raises(ValueError, match="unknown"):
        study.OrderedBridge(bridge, "random")
    with pytest.raises(ValueError, match="canonical"):
        study.OrderedBridge(bridge, "reversed").slot([(1, 2), (0, 3)], [])
    with pytest.raises(ValueError, match="canonical"):
        study.OrderedBridge(bridge, "sorted").slot([(0, 3), (0, 3)], [])


def test_audit_checks_native_order_before_canonicalizing_its_view(monkeypatch):
    raw = delivered([(1, 2), (0, 3)])
    native = {"delivered": raw, "author_counts": [0, 1], "major_paths": [{"nodes": [1, 3, 2]}]}
    record = {"slots": [{"native": native}]}

    def inspect(view):
        row = view["slots"][0]["native"]
        assert row["delivered"] == raw[::-1]
        assert row["author_counts"] == [1, 0]
        assert row["major_paths"] is native["major_paths"]
        return 17

    monkeypatch.setattr(study.audit, "replay", inspect)
    assert study.replay(record, "reversed") == 17
    assert native["delivered"] is raw and native["author_counts"] == [0, 1]
    with pytest.raises(ValueError, match="submission order"):
        study.replay(record, "sorted")
    native["author_counts"] = [1, 0]
    with pytest.raises(ValueError, match="author counts"):
        study.replay(record, "reversed")


def test_allocations_condition_on_pending_set_before_choosing_first_path():
    pairs = [(0, 3), (1, 2)]
    rows = [{"native": {"delivered": delivered(pairs[::-1]), "major_paths": [{"nodes": [1, 0, 2]}]}},
            {"native": {"delivered": delivered(pairs), "major_paths": [{"nodes": [0, 2, 3]}]}},
            {"native": {"delivered": [], "major_paths": []}}]
    counts = study.allocation_counts(rows)
    assert counts[tuple(pairs), (0, 3)] == counts[tuple(pairs), (1, 2)] == counts[(), None] == 1
    assert sum(item["slots"] for item in study.allocation_rows(counts)) == 3
    rows[0]["native"]["major_paths"][0]["nodes"] = [0, 1]
    with pytest.raises(ValueError, match="active demand"):
        study.allocation_counts(rows)


def test_summary_rejects_uncoupled_seeds():
    rows = [{"seed": seed, "order": order, "workload_sha256": "same", "potential_sha256": "physical"}
            for order in study.ORDERS for seed in study.SEEDS]
    rows[-1]["potential_sha256"] = "other"
    with pytest.raises(ValueError, match="unmatched"):
        study.summarize(rows)
    with pytest.raises(ValueError, match="missing"):
        study.summarize(rows[:-1])


def test_native_equal_score_contention_and_full_physical_replay(tmp_path):
    configured = os.environ.get("QCAST_PILOT_BUILD")
    if not configured:
        pytest.skip("set QCAST_PILOT_BUILD to run the pinned native bridge")
    build = Path(configured)
    pairs = [(0, 3), (1, 2)]
    records = []
    with study.pilot.NativeBridge(build, tmp_path/"native-stderr.log") as native:
        for order in study.ORDERS:
            bridge = study.OrderedBridge(native, order)
            bridge.initialize(study.pilot.topology_text("diamond", 2, .5))
            response = bridge.slot(pairs, [True]*8)
            expected = pairs if order == "sorted" else pairs[::-1]
            assert [(r["pair"], r["count"]) for r in response["delivered"]] == [
                (list(expected[0]), 2), (list(expected[1]), 0)]
            data = study.concurrent.run_trajectory("diamond", 2, .5, 7271, "QCAST-Slot", 24, bridge)
            assert study.replay(data, order) == len(data["completions"])
            records.append(data)
    for key in ("requests", "channels", "workload_sha256", "potential_sha256"):
        assert records[0][key] == records[1][key]

"""Deliberate corruptions checked by the independent physical replay."""

from copy import deepcopy

import pytest

from scripts import qcast_pilot as producer
from scripts import qcast_pilot_audit as independent


@pytest.fixture(scope="module")
def records():
    return {arm: producer.run_trajectory("chain", 4, .5, 6271, arm, 24, None)
            for arm in producer.ARMS[1:]}


@pytest.mark.parametrize("arm", producer.ARMS[1:])
def test_independent_full_physical_replay_and_observer(records, arm):
    record = records[arm]
    assert independent.replay(record) == len(record["completions"])
    independent.close(independent.observation(record, 6), producer.observe(record, 6))


@pytest.mark.parametrize("corruption", [
    "potential_digest", "raw_arrival", "selected_duplicate", "false_success",
    "reserved_memory", "block_reason", "swapped_input", "pair_origin",
    "inherited_deadline", "unserved_fifo", "pair_count", "end_completion",
])
def test_independent_replay_rejects_physical_corruption(records, corruption):
    record = deepcopy(records["POQI-Cutoff10-pressure_relaxed"])
    generated = next(row for row in record["slots"] if row["settled"]["generated"])
    swapped = next(row for row in record["slots"] if row["settled"]["swap_log"])
    blocked = next(row for row in record["slots"] if row["blocked"])
    completed = next(row for row in record["slots"] if row["end_completed"])
    if corruption == "potential_digest":
        record["potential_sha256"] = "corrupt"
    elif corruption == "raw_arrival":
        record["requests"][0]["arrival"] += .01
    elif corruption == "selected_duplicate":
        generated["selected"].append(generated["selected"][0])
    elif corruption == "false_success":
        generated["successful"] = []
    elif corruption == "reserved_memory":
        generated["reserved_occupancy"][0] += 1
    elif corruption == "block_reason":
        blocked["blocked"][0]["reason"] = "made_up"
    elif corruption == "swapped_input":
        swapped["settled"]["swap_log"][0]["removed"].reverse()
    elif corruption == "pair_origin":
        generated["settled"]["generated"][0]["pair"]["origins"][0]["neighbor"] = 99
    elif corruption == "inherited_deadline":
        swapped["settled"]["swap_log"][0]["created"][0]["deadline_tick"] += 1
    elif corruption == "unserved_fifo":
        record["pending"].append(0)
    elif corruption == "pair_count":
        generated["remaining_pairs"] += 1
    elif corruption == "end_completion":
        completed["end_completed"] = []
    with pytest.raises(ValueError):
        independent.replay(record)


def test_seed_interval_is_not_pseudoreplicated_over_slots():
    expected_half = 4.302652729911275*(1/3)**.5
    answer = independent.ci([1., 2., 3.])
    assert answer["mean"] == 2
    assert answer["low"] == pytest.approx(2-expected_half)
    assert answer["high"] == pytest.approx(2+expected_half)
    assert answer["n"] == 3
    assert independent.ci([None, None])["n"] == 0


def test_missing_native_internal_connection_is_detected():
    # Synthetic channel graph is just a physical auditing unit test, not a
    # substitute for the recorded native integration runs.
    data = {"topology": "chain", "channels": [[0, 1, 0], [1, 2, 1]]}
    row = {"start_completed": [], "selected": [0, 1], "successful": [0, 1],
           "reserved_occupancy": [1, 2, 1], "swaps": 1,
           "native": {"assigned": [0, 1], "successful": [0, 1], "occupancy": [1, 2, 1],
                      "major_paths": [{"nodes": [0, 1, 2], "width": 1}], "recovery_paths": [],
                      "successful_swap_inputs": [], "swaps": 1}}
    with pytest.raises(ValueError, match="swap total"):
        independent.replay_native_slot(data, row, [], [], [])

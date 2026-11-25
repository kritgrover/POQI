import pytest

from scripts.two_slot_chain_check import check_transitions, replay, simulate_word


def test_every_reachable_inventory_and_queue_representative():
    report = check_transitions()
    assert report["states"] == 29
    assert report["transitions"] == 87
    assert len(report["witnesses"]) == report["states"]


@pytest.mark.parametrize("first,other,partner", [("L", "R", 2), ("R", "L", 0)])
def test_backward_swap_immobilizes_the_opposite_generation_quota(first, other, partner):
    word = first + other + first + "A" + first + other + first + other
    result = simulate_word(word)
    swaps = [event for event in result["events"] if event["kind"] == "swap"]
    assert [event["pivot"] for event in swaps] == [1, 2 - partner]
    reversed_pair, direct_pair = result["live_pairs"]
    assert reversed_pair["parents"] and not direct_pair["parents"]
    for pair, center_origin in [(reversed_pair, 2 - partner), (direct_pair, partner)]:
        assert set(pair["endpoints"]) == {1, partner}
        origins = {entry["node"]: entry["neighbor"] for entry in pair["origins"]}
        assert origins == {1: center_origin, partner: 1}
    rejected = [(e["tick"], e["reason"]) for e in result["events"] if e["kind"] == "reject"]
    assert rejected == [(5, "neighbor_reservation"), (7, "hard_slots"), (8, "hard_slots")]
    assert result["completed_requests"] == 0
    assert result["unserved_requests"] == 1


def test_cached_arrival_and_three_backlogged_completions_return_to_empty():
    assert replay("LRA") == (("empty", 0), 1)
    assert replay("AAALR") == (("empty", 2), 1)
    assert replay("AAALRRLLR") == (("empty", 0), 3)

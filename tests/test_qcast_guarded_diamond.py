from copy import deepcopy

import pytest

from scripts import qcast_guarded_diamond as diamond


def requests(*times):
    return [{"arrival": t} for t in times]


def completions(*times):
    return [{"time": t} for t in times]


def test_gaps_clip_a_carried_queue_and_count_an_unfinished_terminal_spell():
    gaps = diamond.busy_gaps(requests(1, 4, 7), completions(4, 11), 3, 22)
    assert gaps == {"longest_gap": 11, "gaps_at_least_10": 1, "trailing_gap": 11, "right_censored": 1}


def test_gaps_exclude_idle_time_and_do_not_extend_a_completed_spell_to_horizon():
    assert diamond.busy_gaps(requests(2.5, 3, 19), completions(4, 4, 20), 0, 20) == {
        "longest_gap": 1.5, "gaps_at_least_10": 0, "trailing_gap": 0., "right_censored": 0}
    assert diamond.busy_gaps([], [], 10, 20)["longest_gap"] == 0.
    assert diamond.busy_gaps(requests(1, 2), completions(20), 10, 20) == {
        "longest_gap": 10, "gaps_at_least_10": 1, "trailing_gap": 0., "right_censored": 1}


def test_entire_window_without_completion_and_short_final_arrival():
    assert diamond.busy_gaps(requests(2), [], 100, 400) == {
        "longest_gap": 300, "gaps_at_least_10": 1, "trailing_gap": 300, "right_censored": 1}
    assert diamond.busy_gaps(requests(399.8), [], 100, 400)["trailing_gap"] == pytest.approx(.2)


def item(identifier, partner, direction, remote_direction):
    return {"id": identifier, "endpoints": [0, partner], "deadline_tick": None, "admitted_tick": identifier,
            "origins": [{"node": 0, "neighbor": direction}, {"node": partner, "neighbor": remote_direction}]}


def test_concrete_input_search_may_skip_an_older_same_origin_input_on_remote_buffer():
    # At node 0, the physical links are 01,02. The current partner 3 is remote.
    live = {0: item(0, 1, 1, 0), 1: item(1, 3, 1, 2), 2: item(2, 3, 2, 1)}
    assert diamond.pivot_choice(live, 0, 4, False) == (0, 1, 3, 0, 1, True)
    assert diamond.pivot_choice(live, 0, 4, True) == (0, 1, 3, 0, 2, True)


def test_pressure_quota_uses_selected_token_origin_and_preferred_branch_is_also_guarded():
    live = {0: item(0, 1, 1, 0), 1: item(1, 3, 1, 2)}
    assert diamond.pivot_choice(live, 0, 4, False) == (0, 1, 3, 0, 1, True)
    assert diamond.pivot_choice(live, 0, 4, True) is None
    live.update({2: item(2, 1, 1, 0), 3: item(3, 3, 1, 2)})
    # Four entries with the same origin are valid at memory 8, quota four.
    assert diamond.pivot_choice(live, 0, 8, False) == (0, 1, 3, 0, 1, False)
    assert diamond.pivot_choice(live, 0, 8, True) is None


@pytest.mark.parametrize("cutoff", ["Persistent", "Cutoff10"])
def test_two_qubit_full_trajectory_equality_and_independent_check(cutoff):
    records = [diamond.model.run_trajectory("diamond", 2, .5, 7274, f"POQI-{cutoff}-{policy}", 20, None)
               for policy in diamond.POLICIES]
    assert records[0]["slots"] == records[1]["slots"]
    assert records[0]["completions"] == records[1]["completions"]
    assert diamond.replay_physics(records[1]) == diamond.replay_physics(records[0])
    assert diamond.replay_physics(records[1])["first_certified_tick"] == (2 if cutoff == "Persistent" else None)
    if cutoff == "Persistent":
        live = {r["id"]: r for r in records[0]["slots"][-1]["final_inventory"]}
        assert diamond.service_disabled(live, 2, True)
        for r in live.values():
            r["deadline_tick"] = 23
        assert diamond.service_disabled(live, 2, True)  # Physical inactivity lasts only until expiry.


def test_independent_check_rejects_corrupted_swap_ancestry():
    data = diamond.model.run_trajectory("diamond", 4, .5, 7271, "POQI-Persistent-pressure_oriented", 30, None)
    corrupted = deepcopy(data)
    event = next(e for row in corrupted["slots"] for e in row["settled"]["swap_log"])
    event["removed"] = event["removed"][::-1]
    with pytest.raises(ValueError, match="independent swap choice"):
        diamond.replay_physics(corrupted)

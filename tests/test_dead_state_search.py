from scripts.dead_state_search import Arm, TOPOLOGIES, analyse, check_against_simulator, check_copy
from scripts.theory_evidence import certify


def summary(topology, memory, policy, **filters):
    edges, demand = TOPOLOGIES[topology]
    return analyse(Arm(edges, demand, memory, policy, **filters))


def test_two_slot_chain_has_exactly_the_two_mirror_traps_and_the_guard_removes_them():
    report, _, _ = summary("chain", 2, "pressure_relaxed")
    assert report["frozen_inventories"] == ["01[slots 0>1,1>2] 01", "12[slots 1>0,2>1] 12"]
    assert report["verdict"] == "dead classes only"
    assert report["lockup_reachable_from_every_state"]
    assert summary("chain", 2, "pressure_oriented")[0]["verdict"] == "no lockup"


def test_uniform_budgets_above_two_have_no_lockup_on_the_three_node_chain():
    for memory in (3, 4, 5, 6):
        assert summary("chain", memory, "pressure_relaxed")[0]["verdict"] == "no lockup"


def test_lockup_needs_a_two_slot_endpoint_facing_a_one_slot_reservation():
    assert summary("chain", (2, 3, 2), "pressure_relaxed")[0]["verdict"] == "dead classes only"
    assert summary("chain", (2, 3, 2), "pressure_oriented")[0]["verdict"] == "no lockup"
    assert summary("chain", (3, 2, 3), "pressure_relaxed")[0]["verdict"] == "no lockup"
    assert summary("chain", (2, 4, 2), "pressure_relaxed")[0]["verdict"] == "no lockup"


def test_one_slot_endpoints_cannot_feed_a_large_repeater_under_either_policy():
    for policy in ("pressure_relaxed", "pressure_oriented"):
        assert summary("chain", (1, 3, 1), policy)[0]["verdict"] == "no lockup"
        assert summary("chain", (1, 4, 1), policy)[0]["verdict"] == "dead classes only"


def test_diamond_search_reproduces_the_archived_frozen_inventories():
    for policy in ("pressure_relaxed", "pressure_oriented"):
        report, _, _ = summary("diamond", 2, policy)
        assert report["frozen_inventories"] == ["02 13[slots 1>0,3>2] 13", "02[slots 0>1,2>3] 02 13"]
        partial = [c for c in report["closed_classes"] if c["served"] and c["starved"]]
        assert [c["served"] for c in partial] == [[[0, 1]]]
        assert report["lockup_reachable_from_every_state"]


def test_each_published_condition_fails_on_one_small_network():
    # Orientation does not help on the diamond. The no-shortcut filter does.
    assert summary("diamond", 2, "pressure_oriented", no_shortcut=True)[0]["verdict"] == "no lockup"
    # The no-shortcut filter does not help on a four-node chain. Orientation does.
    assert summary("chain4", 2, "pressure_relaxed", no_shortcut=True)[0]["verdict"] == "dead classes only"
    assert summary("chain4", 2, "pressure_oriented")[0]["verdict"] == "no lockup"
    assert summary("chain4", 3, "pressure_relaxed")[0]["verdict"] == "dead classes only"


def test_five_cycle_with_one_demand_pair_locks_under_every_rule_at_two_slots():
    for policy, filters in (("pressure_relaxed", {}), ("pressure_oriented", {"no_shortcut": True}),
                            ("pressure_relaxed", {"geodesic": True})):
        assert summary("cycle5", 2, policy, **filters)[0]["verdict"] != "no lockup"


def test_driver_matches_the_public_simulator_and_the_copied_loop_matches_the_original():
    assert check_against_simulator("chain", 3, "pressure_relaxed", samples=20, length=25) == 20
    assert check_against_simulator("chain4", 2, "pressure_oriented", samples=10, length=25) == 10
    edges, demand = TOPOLOGIES["diamond"]
    _, graph, _ = summary("diamond", 2, "pressure_oriented")
    check_copy(Arm(edges, demand, 2, "pressure_oriented"), graph)


def test_uncapped_diamond_freeze_certificates_reach_both_mirrors():
    witnesses = certify("diamond", "pressure_oriented", 2)
    duplicates = []
    for witness in witnesses:
        assert witness["public_next_events_checked"] == 14
        assert witness["backlogs_per_class_checked"] == [0, 7]
        pairs = [entry["endpoints"] for entry in witness["frozen_inventory"]]
        duplicates.append(next(pair for pair in pairs if pairs.count(pair) == 2))
    assert sorted(duplicates) == [[0, 2], [1, 3]]

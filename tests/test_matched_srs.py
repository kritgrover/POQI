from scripts.matched_srs import Scenario, design, pair_outcomes, sum_classes, workload


def test_window_includes_old_backlog_and_censored_waits():
    # Arrival 1 completes in the window. Arrival 5 is fulfilled immediately.
    # Arrival 6 qualifies for full follow-up and waits past the 3-slot cap.
    row = pair_outcomes([1, 5, 6, 9], [5, 5], warmup=5, horizon=10, followup=3)
    assert row == {
        "offered": 3, "completed": 2, "end_backlog": 2, "unfinished_window_arrivals": 2,
        "restricted_wait_sum": 3, "restricted_wait_count": 2,
        "intervals": [4], "right_censored_length": 4,
    }
    # Arrival at horizon minus follow-up belongs to the restricted-wait cohort.
    row = pair_outcomes([0, 5, 7], [7], warmup=5, horizon=10, followup=3)
    assert row["intervals"] == [2, 3]
    assert row["restricted_wait_sum"] == 6
    assert row["restricted_wait_count"] == 2


def test_active_and_silent_demand_classes_remain_distinct():
    active = pair_outcomes([0], [], 5, 100, 50)
    silent = pair_outcomes([], [], 5, 100, 50)
    summary = sum_classes([dict(rate=.1, **active), dict(rate=.1, **silent)], 95)
    assert summary["starved_classes"] == 1
    assert summary["outage_share"] == .5
    assert summary["restricted_wait"] is None
    assert sum_classes([], 95)["satisfaction"] is None


def test_adding_rare_demand_preserves_core_arrivals_and_physical_inputs():
    sparse = workload(Scenario(), 12101, 200)
    dense = workload(Scenario(background=.02), 12101, 200)
    assert sparse[:2] == dense[:2]
    assert all(sparse[3][pair] == dense[3][pair] for pair in sparse[1])
    assert [tuple(links.items()) for links, _ in sparse[4]] == [
        tuple(links.items()) for links, _ in dense[4]]
    assert len(dense[2]) == 28
    assert len(design()) == len({c.name for c in design()}) == 24

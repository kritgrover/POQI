from scripts.guarded_chain_check import check_transitions, replay


def test_enumerates_idle_stock_and_transitions_into_and_out_of_busy_periods():
    report = check_transitions()
    assert report["states"] == 17
    assert report["transitions"] == 51


def test_consuming_a_cached_pair_leaves_direct_stock_until_the_next_event():
    assert replay("LRLR") == (("LRV", 0), 0)
    assert replay("LRLRA") == (("LR", 0), 1)
    assert replay("LRLRAA") == (("empty", 0), 2)
    assert replay("LRLRAAA") == (("empty", 1), 2)

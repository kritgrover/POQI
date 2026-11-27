from scripts.cutoff_outage_analysis import run


def test_every_outage_ends_one_cutoff_after_its_oldest_ancestor_and_serves_nothing():
    original = run(("pressure_relaxed", 10.0, 0.5, 11271, 1500.0, 100.0))
    assert original["outages"] > 10
    assert original["outage_plus_age_minus_cutoff"] < 1e-9
    assert original["completions_during_outage"] == 0
    assert 8 < original["mean_outage"] < 10

    guarded = run(("pressure_oriented", 10.0, 0.5, 11271, 1500.0, 100.0))
    assert guarded["outages"] == 0 and guarded["outage_fraction"] == 0
    assert guarded["mean_latency"] < original["mean_latency"]

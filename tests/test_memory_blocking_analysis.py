"""Sizing checks and reanalysis of an actual small, independent-seed experiment."""

from collections import Counter
import gzip
import json
import shutil

import pytest

from scripts import memory_blocking_analysis as analysis


def calibration(scenario, loads):
    return {"scenario": scenario, "origins": [
        {"node": node, "neighbor": neighbor, "offered_load": load}
        for (node, neighbor), load in loads.items()]}


def test_direct_control_sizes_ten_erlangs_without_double_counting_endpoints():
    observed = calibration("direct_cutoff10", {(0, 1): 10, (1, 0): 10})
    design = analysis.select_budgets(observed, .01)
    assert design["mean_budget"] == 10
    assert design["erlang_budget"] == 18
    assert analysis.predict(observed, 17)["blocking"] > .01
    assert analysis.predict(observed, 18)["blocking"] < .01
    prediction = analysis.predict(observed, 10)
    assert prediction["blocking"] == pytest.approx(.2145823431073473)
    assert prediction["dependence_low"] == prediction["dependence_high"] == prediction["blocking"]
    assert prediction["tail_blocking"] is None
    assert design["tail_budget"] is None


def test_mean_sizing_respects_each_reservation_not_just_total_load():
    observed = calibration("chain_cutoff10", {(0, 1): 2, (1, 0): 3.4, (1, 2): 3.4, (2, 1): 2})
    graph, _, _ = analysis.specification("chain_cutoff10")
    assert [analysis.quota(graph, 1, neighbor, 7) for neighbor in (0, 2)] == [4, 3]
    # Seven slots exceed the pivot's total load 6.8, but its second quota is too small.
    design = analysis.select_budgets(observed, .9)
    assert design["mean_budget"] == 8
    assert design["erlang_budget"] < design["mean_budget"]
    assert {design["mean_budget"], design["erlang_budget"]}.issubset(design["capacities"])


def test_chain_prediction_uses_independent_endpoint_approximation_and_union_bounds():
    observed = calibration("chain_cutoff10", {(0, 1): 1, (1, 0): 1, (1, 2): 1, (2, 1): 1})
    # Each edge sees an outer capacity 2 (B=1/5), pivot quota 1 (B=1/2).
    prediction = analysis.predict(observed, 2)
    assert {k: prediction[k] for k in ("blocking", "dependence_low", "dependence_high")} == pytest.approx(
        {"blocking": .6, "dependence_low": .5, "dependence_high": .7})
    assert prediction["tail_blocking"] is None
    assert analysis.predict(observed, None) == {
        "blocking": 0, "tail_blocking": 0, "dependence_low": 0, "dependence_high": 0}


def test_tiny_chain_loss_remains_positive_without_subtraction_cancellation():
    observed = calibration("chain_cutoff10", {(0, 1): 1, (1, 0): 1, (1, 2): 1, (2, 1): 1})
    prediction = analysis.predict(observed, 100)
    assert 0 < prediction["blocking"] < 1e-50
    assert prediction["dependence_low"] <= prediction["blocking"] <= prediction["dependence_high"]


def holding_observation(histogram):
    return {"offered": sum(histogram.values()), "required_capacity_histogram": [
        {"capacity": capacity, "attempts": attempts} for capacity, attempts in histogram.items()],
        "origins": [{"node": node, "neighbor": 1 - node, "cohort_arrivals": 2,
                     "cohort_censored": 0, "cohort_departed_holding_sum": 4,
                     "cohort_censored_holding_sum": 0, "cohort_restricted_mean": 2}
                    for node in (0, 1)]}


def test_arrival_capacity_tail_pools_counts_and_uses_strict_threshold():
    first = holding_observation({1: 90, 3: 5, 5: 5})
    second = holding_observation({1: 80, 3: 10, 5: 10})
    fitted = analysis.calibrate("direct_cutoff10", [first, second])
    assert fitted["required_capacity_histogram"] == [
        {"capacity": 1, "attempts": 170}, {"capacity": 3, "attempts": 15}, {"capacity": 5, "attempts": 15}]
    # R=c is admitted; only R>c contributes to predicted blocking.
    assert analysis.predict(fitted, 0)["tail_blocking"] == 1
    assert analysis.predict(fitted, 1)["tail_blocking"] == pytest.approx(.15)
    assert analysis.predict(fitted, 3)["tail_blocking"] == pytest.approx(.075)
    assert analysis.predict(fitted, 5)["tail_blocking"] == 0
    design = analysis.select_budgets(fitted, .10)
    assert design["tail_budget"] == 3
    assert analysis.predict(fitted, design["tail_budget"] - 1)["tail_blocking"] > .10
    assert analysis.predict(fitted, design["tail_budget"])["tail_blocking"] <= .10
    assert {2, 3, 4}.issubset(design["capacities"])


def test_capacity_histogram_must_account_for_all_calibration_attempts():
    observed = holding_observation({1: 90, 3: 10})
    observed["offered"] += 1
    with pytest.raises(ValueError, match="count mismatch"):
        analysis.calibrate("direct_cutoff10", [observed])


@pytest.mark.parametrize("corruption", ["partial", "duplicate"])
def test_capacity_histogram_cannot_silently_drop_calibration_observations(corruption):
    first = holding_observation({1: 90, 3: 10})
    second = holding_observation({1: 80, 3: 20})
    if corruption == "partial":
        second.pop("required_capacity_histogram")
    else:
        second["required_capacity_histogram"] = [
            {"capacity": 1, "attempts": 80}, {"capacity": 1, "attempts": 20}]
    with pytest.raises(ValueError):
        analysis.calibrate("direct_cutoff10", [first, second])


def test_overlapping_seed_sets_fail_before_creating_an_experiment(tmp_path):
    output = tmp_path / "overlap"
    with pytest.raises(ValueError, match="overlap"):
        analysis.run_suite(output, horizon=60, warmup=10, calibration_runs=2, validation_runs=2,
                           calibration_seed=100, validation_seed=101)
    assert not output.exists()


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    output = tmp_path_factory.mktemp("blocking-analysis") / "experiment"
    analysis.run_suite(output, horizon=60, warmup=10, calibration_runs=2, validation_runs=2,
                       calibration_seed=5101, validation_seed=6101)
    return output


@pytest.fixture
def copied_experiment(experiment, tmp_path):
    return shutil.copytree(experiment, tmp_path / "experiment")


def read_manifest(directory):
    return json.loads((directory / "manifest.json").read_text())


def write_manifest(directory, manifest):
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def read_case(directory, *, scenario="direct_cutoff10", phase="validation"):
    manifest = read_manifest(directory)
    case = next(r for r in manifest["runs"] if r["scenario"] == scenario and r["phase"] == phase)
    path = directory / case["artifact"]
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        saved = json.load(stream)
    return manifest, case, path, saved


def write_case(path, saved):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(saved, stream)


def test_actual_small_suite_reanalyses_and_exports(experiment, tmp_path):
    report = analysis.build_report(experiment)
    manifest = read_manifest(experiment)
    assert report["validated_runs"] == len(manifest["runs"]) > 60
    assert set(report["calibration_seeds"]).isdisjoint(report["validation_seeds"])
    assert all(r["n"] == 2 for r in report["summary"])
    for scenario in analysis.SCENARIOS:
        rows = [r for r in report["summary"] if r["scenario"] == scenario]
        assert any(r["capacity"] is None and r["blocking_probability"]["mean"] == 0 for r in rows)
        if scenario.startswith("chain"):
            assert all(r["zero_completion_runs"] == 2 for r in rows if r["capacity"] in (1, 2, 3))
    output = analysis.write_report(report, tmp_path / "report")
    assert (output / "blocking.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert json.loads((output / "blocking.json").read_text())["validated_runs"] == report["validated_runs"]
    with pytest.raises(FileExistsError):
        analysis.write_report(report, output)


def test_full_suite_tail_budgets_use_only_unlimited_calibration_attempts(experiment):
    manifest = read_manifest(experiment)
    for scenario in analysis.SCENARIOS:
        counts = Counter()
        for case in manifest["runs"]:
            if case["scenario"] == scenario and case["phase"] == "calibration":
                assert case["capacity"] is None
                assert case["seed"] in manifest["calibration_seeds"]
                with gzip.open(experiment / case["artifact"], "rt", encoding="utf-8") as stream:
                    observed = json.load(stream)["observed"]
                histogram = observed["required_capacity_histogram"]
                assert sum(r["attempts"] for r in histogram) == observed["offered"]
                counts.update({r["capacity"]: r["attempts"] for r in histogram})
        # Independently invert the empirical, discrete R distribution; validation
        # attempts do not enter this calculation or the selected capacity.
        target_count = manifest["target"] * sum(counts.values())
        expected = next(c for c in range(max(counts) + 1)
                        if sum(n for required, n in counts.items() if required > c) <= target_count)
        design = manifest["scenarios"][scenario]
        assert design["tail_budget"] == expected
        assert expected in design["capacities"]
        assert sum(n for required, n in counts.items() if required >= expected) > target_count


@pytest.mark.parametrize("kind,message", [("missing", "missing experiment"), ("duplicate", "duplicate"),
                                          ("incomplete", "incomplete"), ("overlap", "overlap")])
def test_incomplete_or_duplicate_coverage_is_rejected(copied_experiment, kind, message):
    manifest = read_manifest(copied_experiment)
    if kind == "missing":
        manifest["runs"].pop()
    elif kind == "duplicate":
        manifest["runs"].append(manifest["runs"][0])
    elif kind == "incomplete":
        manifest["status"] = "running"
    else:
        manifest["validation_seeds"] = manifest["calibration_seeds"]
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError, match=message):
        analysis.build_report(copied_experiment)


@pytest.mark.parametrize("field,value", [("swap_policy", "physical"), ("cutoff_time", 20),
                                        ("admission_policy", "tail_drop"), ("distillation_pairs", 2),
                                        ("initial_pairs", 1)])
def test_simulation_protocol_change_is_rejected(copied_experiment, field, value):
    _, _, path, saved = read_case(copied_experiment)
    saved["simulation"][field] = value
    write_case(path, saved)
    with pytest.raises(ValueError, match="protocol"):
        analysis.build_report(copied_experiment)


def test_case_warmup_must_match_experiment_protocol(copied_experiment):
    manifest, case, path, saved = read_case(copied_experiment)
    case["warmup"] += 1
    saved["case"] = case
    write_case(path, saved)
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError, match="protocol"):
        analysis.build_report(copied_experiment)


def test_saved_observation_corruption_is_rejected(copied_experiment):
    _, _, path, saved = read_case(copied_experiment)
    saved["observed"]["blocking_probability"] += .01
    write_case(path, saved)
    with pytest.raises(ValueError, match="event replay"):
        analysis.build_report(copied_experiment)


@pytest.mark.parametrize("field", ["calibration_seeds", "validation_seeds"])
def test_duplicate_seed_list_is_not_extra_replication(copied_experiment, field):
    manifest = read_manifest(copied_experiment)
    manifest[field].append(manifest[field][0])
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError, match="seed"):
        analysis.build_report(copied_experiment)


def test_extra_scenario_cannot_be_silently_ignored(copied_experiment):
    manifest = read_manifest(copied_experiment)
    manifest["scenarios"]["unreported"] = manifest["scenarios"]["direct_cutoff10"]
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError, match="scenario"):
        analysis.build_report(copied_experiment)


def replace_simulation(saved, case, *, seed=None, ticks=1000000):
    graph, demand, cutoff = analysis.specification(case["scenario"])
    data = analysis.run_simulation(graph, demand, memory_slots=case["capacity"], cutoff_time=cutoff,
                                   horizon=case["horizon"], seed=case["seed"] if seed is None else seed,
                                   ticks_per_time_unit=ticks, admission_policy="reserved",
                                   swap_policy="none" if not demand else "balancing",
                                   record_events=True).to_dict()
    data["seed"] = case["seed"]
    saved["simulation"] = data
    saved["observed"] = analysis.observe_blocking(data, warmup=case["warmup"], cohort_end=case["cohort_end"],
                                                physical_neighbors={n: list(graph.neighbors(n)) for n in graph})


def test_valid_but_different_inputs_across_capacities_are_rejected(copied_experiment):
    _, case, path, saved = read_case(copied_experiment)
    replace_simulation(saved, case, seed=case["seed"] + 99)
    write_case(path, saved)
    with pytest.raises(ValueError, match="unmatched inputs"):
        analysis.build_report(copied_experiment)


def test_self_consistent_different_tick_resolution_breaks_protocol(copied_experiment):
    _, case, path, saved = read_case(copied_experiment, phase="calibration")
    replace_simulation(saved, case, ticks=1000)
    write_case(path, saved)
    with pytest.raises(ValueError, match="protocol"):
        analysis.build_report(copied_experiment)

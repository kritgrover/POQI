"""Complete robustness coverage and seed-paired horizon/memory comparisons."""

import gzip
import json
from math import sqrt
import shutil
from statistics import mean, stdev

import networkx as nx
import pytest
from scipy.stats import t

from poqi.simulation import run_simulation
from scripts import memory_robustness_analysis as analysis


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    output = tmp_path_factory.mktemp("robustness-analysis") / "experiment"
    analysis.run_suite(output, horizon=30, warmup=5, split=15,
                       replicates=2, seed=13001, workers=1)
    return output


@pytest.fixture(scope="module")
def report(experiment):
    return analysis.build_report(experiment)


@pytest.fixture
def copied_experiment(experiment, tmp_path):
    return shutil.copytree(experiment, tmp_path / "experiment")


def read_manifest(directory):
    return json.loads((directory / "manifest.json").read_text())


def write_manifest(directory, manifest):
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def read_case(directory):
    manifest = read_manifest(directory)
    case = manifest["runs"][0]
    path = directory / case["artifact"]
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        saved = json.load(stream)
    return manifest, case, path, saved


def write_case(path, saved):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(saved, stream)


def select(rows, **criteria):
    matches = [row for row in rows if all(row[k] == v for k, v in criteria.items())]
    assert len(matches) == 1, criteria
    return matches[0]


def manual_interval(values):
    estimate = mean(values)
    half_width = t.ppf(.975, len(values) - 1) * stdev(values) / sqrt(len(values))
    return estimate, [estimate - half_width, estimate + half_width]


def assert_interval(actual, values):
    if any(value is None for value in values):
        assert actual == {"mean": None, "ci95": None}
        return
    estimate, bounds = manual_interval(values)
    assert actual["mean"] == pytest.approx(estimate)
    assert actual["ci95"] == pytest.approx(bounds)


def test_actual_smoke_has_complete_conditions_and_paired_controls(experiment, report):
    manifest = read_manifest(experiment)
    assert report["validated_runs"] == len(manifest["runs"]) == 120
    assert report["unlimited_equivalent_pairs"] == 12
    assert len(report["summary"]) == 120
    assert len(report["paired"]) == len(report["horizon_changes"]) == 60
    assert len(report["memory_comparisons"]) == 24
    assert len(report["observations"]) == 240
    assert all(row["n"] == 2 for row in report["summary"])
    assert {row["window"] for row in report["observations"]} == {"early", "late"}
    for row in report["paired"]:
        if row["capacity"] is None:
            for metric in ("throughput", "blocking_probability", "mean_backlog", "final_backlog"):
                assert row[metric] == {"mean": 0.0, "ci95": [0.0, 0.0]}


def test_report_exports_numeric_tables_and_error_bar_figure(report, tmp_path):
    output = analysis.write_report(report, tmp_path / "report")
    assert any(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in output.glob("*.png"))
    for name in ("observations", "summary", "paired", "horizon_changes", "memory_comparisons"):
        assert (output / f"{name}.csv").is_file()
    with pytest.raises(FileExistsError):
        analysis.write_report(report, output)


def test_zero_service_runs_and_undefined_ratios_remain_in_group(report):
    row = select(report["summary"], scenario="chain_lossless", demand=1.0,
                 capacity=2, policy="balancing", window="late")
    assert row["n"] == 2
    assert row["throughput"] == {"mean": 0.0, "ci95": [0.0, 0.0]}
    assert row["mean_backlog"]["mean"] > 0
    assert row["swaps_per_completion"] == {"mean": None, "ci95": None}
    observed = [r for r in report["observations"] if r["scenario"] == "chain_lossless"
                and r["demand"] == 1.0 and r["capacity"] == 2
                and r["policy"] == "balancing" and r["window"] == "late"]
    assert len(observed) == 2
    assert all(r["completed_requests"] == 0 and r["zero_service"] for r in observed)


def test_policy_differences_use_independent_seeds_as_replicates(report):
    for row in report["paired"]:
        criteria = {k: row[k] for k in ("scenario", "demand", "capacity", "window")}
        observed = [r for r in report["observations"] if all(r[k] == v for k, v in criteria.items())]
        seeds = {r["seed"] for r in observed}
        assert row["n"] == len(seeds) == 2
        for metric in ("throughput", "mean_backlog", "backlog_growth_rate"):
            differences = [select(observed, seed=seed, policy="pressure_relaxed")[metric]
                           - select(observed, seed=seed, policy="balancing")[metric]
                           for seed in sorted(seeds)]
            assert_interval(row[metric], differences)


def test_horizon_changes_pair_correlated_windows_within_each_seed(report):
    for row in report["horizon_changes"]:
        # Raw swap totals cannot be compared across unequal-duration windows.
        assert "swaps" not in row and "pressure_relaxed_swaps" not in row
        criteria = {k: row[k] for k in ("scenario", "demand", "capacity", "policy")}
        observed = [r for r in report["observations"] if all(r[k] == v for k, v in criteria.items())]
        seeds = {r["seed"] for r in observed}
        # Two seeds, not four independent early/late observations.
        assert row["n"] == len(seeds) == 2
        for metric in ("throughput", "blocking_probability", "mean_backlog", "final_backlog",
                       "backlog_growth_rate", "swaps_per_completion"):
            differences = []
            for seed in sorted(seeds):
                late = select(observed, seed=seed, window="late")[metric]
                early = select(observed, seed=seed, window="early")[metric]
                differences.append(None if late is None or early is None else late - early)
            assert_interval(row[metric], differences)


def test_prespecified_memory_comparisons_are_paired_across_budgets(report):
    assert {(r["pressure_capacity"], r["balancing_capacity"])
            for r in report["memory_comparisons"]} == {(3, 4), (4, 8)}
    for row in report["memory_comparisons"]:
        assert row["memory_reduction_fraction"] == pytest.approx(
            1 - row["pressure_capacity"] / row["balancing_capacity"])
        criteria = {k: row[k] for k in ("scenario", "demand", "window")}
        observed = [r for r in report["observations"] if all(r[k] == v for k, v in criteria.items())]
        seeds = {r["seed"] for r in observed}
        assert row["n"] == len(seeds) == 2
        for metric in ("throughput", "mean_backlog", "backlog_growth_rate"):
            differences = [select(observed, seed=seed, policy="pressure_relaxed",
                                  capacity=row["pressure_capacity"])[metric]
                           - select(observed, seed=seed, policy="balancing",
                                    capacity=row["balancing_capacity"])[metric]
                           for seed in sorted(seeds)]
            assert_interval(row[metric], differences)


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "incomplete"])
def test_incomplete_duplicate_or_running_experiments_are_rejected(copied_experiment, corruption):
    manifest = read_manifest(copied_experiment)
    if corruption == "missing":
        manifest["runs"].pop()
    elif corruption == "duplicate":
        manifest["runs"].append(manifest["runs"][0])
    else:
        manifest["status"] = "running"
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_file_order_does_not_change_policy_horizon_or_memory_pairing(copied_experiment, report):
    manifest = read_manifest(copied_experiment)
    manifest["runs"].reverse()
    write_manifest(copied_experiment, manifest)
    shuffled = analysis.build_report(copied_experiment)
    for field in ("paired", "horizon_changes", "memory_comparisons"):
        assert shuffled[field] == report[field]


@pytest.mark.parametrize("field,value", [("swap_policy", "physical"), ("cutoff_time", 123),
                                         ("admission_policy", "tail_drop"), ("ticks_per_time_unit", 100)])
def test_wrong_simulation_protocol_is_rejected(copied_experiment, field, value):
    _, _, path, saved = read_case(copied_experiment)
    saved["simulation"][field] = value
    write_case(path, saved)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_corrupt_cached_window_cannot_override_events(copied_experiment):
    _, _, path, saved = read_case(copied_experiment)
    saved["observed"]["windows"][0]["throughput"] += 1
    write_case(path, saved)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_window_configuration_mismatch_is_rejected(copied_experiment):
    manifest = read_manifest(copied_experiment)
    manifest["split"] += 1
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_duplicate_seeds_are_rejected(copied_experiment):
    manifest = read_manifest(copied_experiment)
    manifest["seeds"][1] = manifest["seeds"][0]
    write_manifest(copied_experiment, manifest)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_valid_trajectory_with_relabelled_unmatched_inputs_is_rejected(copied_experiment):
    _, case, path, saved = read_case(copied_experiment)
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    data = run_simulation(graph, {(0, 2): case["demand"]}, memory_slots=case["capacity"],
                          cutoff_time=None if case["scenario"] == "chain_lossless" else 10,
                          horizon=case["horizon"], seed=case["seed"] + 100,
                          ticks_per_time_unit=1000000, admission_policy="reserved",
                          swap_policy=case["policy"], record_events=True).to_dict()
    data["seed"] = case["seed"]
    saved["simulation"] = data
    saved["observed"] = analysis.observe_robustness(data, warmup=case["warmup"], split=case["split"])
    write_case(path, saved)
    with pytest.raises(ValueError, match="unmatched"):
        analysis.build_report(copied_experiment)

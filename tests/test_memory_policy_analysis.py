"""Matched-policy statistics and complete event-log reanalysis."""

import gzip
import json
import shutil

import networkx as nx
import pytest

from poqi.simulation import run_simulation
from scripts import memory_policy_analysis as analysis


def direct_trace(events, *, horizon=5):
    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return run_simulation(graph, {(0, 1): 1.0}, horizon=horizon, ticks_per_time_unit=100,
                          trace=events, swap_policy="balancing").to_dict()


def event(time, kind, count=1):
    return {"time": time, "kind": kind, "endpoints": [0, 1], "count": count}


def test_warmup_backlog_integral_retains_old_unfinished_requests():
    data = direct_trace([event(0, "request", 3), event(1, "generate"),
                         event(2, "request"), event(3, "generate")])
    observed = analysis.observe_policy(data, warmup=1.5)
    # Queue sizes: 2 on [1.5,2), 3 on [2,3), 2 on [3,5).
    assert observed["mean_backlog"] == pytest.approx(8 / 3.5)
    assert observed["final_backlog"] == 2
    assert observed["completed_requests"] == 1
    assert observed["throughput"] == pytest.approx(1 / 3.5)
    assert observed["swaps"] == 0
    assert observed["swaps_per_completion"] == 0
    assert observed["backlog_growth_rate"] == 0
    pair = observed["per_pair"][0]
    assert pair["offered_requests"] == pair["completed_requests"] == 1
    assert pair["final_backlog"] == 2


def test_warmup_boundary_events_are_included_and_same_tick_service_has_no_area():
    data = direct_trace([event(1, "request"), event(1, "generate")], horizon=3)
    observed = analysis.observe_policy(data, warmup=1)
    assert observed["completed_requests"] == 1
    assert observed["per_pair"][0]["offered_requests"] == 1
    assert observed["mean_backlog"] == 0
    assert observed["final_backlog"] == 0


def test_zero_service_keeps_backlog_and_undefined_swaps_per_completion():
    data = direct_trace([event(1, "request", 2)])
    observed = analysis.observe_policy(data)
    assert observed["completed_requests"] == 0
    assert observed["mean_backlog"] == pytest.approx(8 / 5)
    assert observed["final_backlog"] == 2
    assert observed["swaps_per_completion"] is None


def test_fifo_replay_rejects_reordered_completion_identifiers():
    data = direct_trace([event(0, "request", 2), event(1, "generate", 2)])
    first, second = [row for row in data["events"] if row["kind"] == "complete"]
    first["request_id"], second["request_id"] = second["request_id"], first["request_id"]
    with pytest.raises(ValueError, match="FIFO"):
        analysis.observe_policy(data)


def pressure_trace():
    graph, demand, _, _ = analysis.specification("chain_lossless")
    trace = [{"time": 0, "kind": "request", "endpoints": [0, 2]},
             {"time": 1, "kind": "generate", "endpoints": [0, 1]},
             {"time": 2, "kind": "generate", "endpoints": [1, 2]}]
    return run_simulation(graph, demand, horizon=5, memory_slots=2, trace=trace,
                          swap_policy="pressure_relaxed", ticks_per_time_unit=100).to_dict()


def test_relaxation_counter_is_scoped_to_observation_window():
    data = pressure_trace()
    observed = analysis.observe_policy(data)
    assert observed["swaps"] == observed["pressure_relaxed_swaps"] == 1
    assert observed["completed_requests"] == observed["swaps_per_completion"] == 1
    after = analysis.observe_policy(data, warmup=3)
    assert after["swaps"] == after["pressure_relaxed_swaps"] == 0
    assert after["completed_requests"] == 0
    assert after["swaps_per_completion"] is None


@pytest.mark.parametrize("corruption", ["count", "missing_count", "boolean_count", "consistent_flag_and_count"])
def test_replay_rejects_corrupt_relaxation_accounting(corruption):
    data = pressure_trace()
    if corruption == "count":
        data["pressure_relaxed_swaps"] += 1
    elif corruption == "missing_count":
        del data["pressure_relaxed_swaps"]
    elif corruption == "boolean_count":
        data["pressure_relaxed_swaps"] = True
    else:
        # A matching counter cannot conceal a swap that needed the relaxed rule.
        next(row for row in data["events"] if row["kind"] == "swap")["pressure_relaxed"] = False
        data["pressure_relaxed_swaps"] = 0
    with pytest.raises(ValueError, match="relaxed"):
        analysis.observe_policy(data)


def test_paired_difference_matches_seed_ids_not_record_order():
    first = [{"seed": 11, "throughput": 1.0}, {"seed": 22, "throughput": 10.0}]
    second = [{"seed": 22, "throughput": 12.0}, {"seed": 11, "throughput": 3.0}]
    result = analysis.paired_difference(second, first, "throughput")
    assert result == {"mean": 2.0, "ci95": [2.0, 2.0]}


@pytest.mark.parametrize("second", [
    [{"seed": 11, "throughput": 3.0}],
    [{"seed": 11, "throughput": 3.0}, {"seed": 11, "throughput": 4.0}],
    [{"seed": 11, "throughput": 3.0}, {"seed": 33, "throughput": 4.0}],
])
def test_invalid_pair_coverage_fails(second):
    first = [{"seed": 11, "throughput": 1.0}, {"seed": 22, "throughput": 10.0}]
    with pytest.raises(ValueError):
        analysis.paired_difference(second, first, "throughput")


def test_undefined_ratios_are_not_dropped_from_group_or_paired_statistics():
    stalled = analysis.observe_policy(direct_trace([event(0, "request")]))
    served = analysis.observe_policy(direct_trace([event(0, "request"), event(1, "generate")]))
    summary = analysis.summarize_group([stalled, served])
    assert summary["n"] == 2
    assert summary["zero_completion_runs"] == summary["undefined_swap_ratios"] == 1
    assert summary["swaps_per_completion"] == {"mean": None, "ci95": None}
    result = analysis.paired_difference(
        [{**served, "seed": 11}, {**served, "seed": 22}],
        [{**stalled, "seed": 11}, {**served, "seed": 22}], "swaps_per_completion")
    assert result == {"mean": None, "ci95": None}


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    output = tmp_path_factory.mktemp("policy-analysis") / "experiment"
    analysis.run_suite(output, horizon=30, warmup=5, replicates=2, seed=8101)
    return output


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


def test_actual_suite_has_full_paired_coverage_and_exports(experiment, tmp_path):
    report = analysis.build_report(experiment)
    manifest = read_manifest(experiment)
    assert report["validated_runs"] == len(manifest["runs"]) == 108
    assert report["unlimited_equivalent_pairs"] == 6
    assert len(report["summary"]) == 54
    assert len(report["paired"]) == 36
    assert len(report["per_pair"]) == 90
    assert all(row["n"] == 2 for row in report["summary"])
    stalled = next(row for row in report["summary"] if row["scenario"] == "chain_lossless"
                   and row["capacity"] == 2 and row["policy"] == "balancing")
    assert stalled["zero_completion_runs"] == stalled["undefined_swap_ratios"] == 2
    assert stalled["throughput"] == {"mean": 0.0, "ci95": [0.0, 0.0]}
    assert stalled["mean_backlog"]["mean"] > 0
    for row in report["paired"]:
        if row["capacity"] is None and row["policy"] == "pressure_relaxed":
            for metric in ("throughput", "blocking_probability", "mean_backlog", "final_backlog"):
                assert row[metric] == {"mean": 0.0, "ci95": [0.0, 0.0]}
    output = analysis.write_report(report, tmp_path / "report")
    assert any(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in output.glob("*.png"))
    with pytest.raises(FileExistsError):
        analysis.write_report(report, output)


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "incomplete"])
def test_incomplete_or_duplicate_cases_are_rejected(copied_experiment, corruption):
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


def test_report_order_does_not_change_paired_estimates(copied_experiment):
    original = analysis.build_report(copied_experiment)
    manifest = read_manifest(copied_experiment)
    manifest["runs"].reverse()
    write_manifest(copied_experiment, manifest)
    shuffled = analysis.build_report(copied_experiment)
    assert shuffled["paired"] == original["paired"]


@pytest.mark.parametrize("field,value", [("swap_policy", "physical"), ("cutoff_time", 123),
                                         ("admission_policy", "tail_drop"), ("ticks_per_time_unit", 100)])
def test_wrong_simulation_protocol_is_rejected(copied_experiment, field, value):
    _, _, path, saved = read_case(copied_experiment)
    saved["simulation"][field] = value
    write_case(path, saved)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_corrupt_observation_cannot_override_raw_events(copied_experiment):
    _, _, path, saved = read_case(copied_experiment)
    saved["observed"]["throughput"] += 1
    write_case(path, saved)
    with pytest.raises(ValueError):
        analysis.build_report(copied_experiment)


def test_correctly_replayed_run_with_unmatched_inputs_is_rejected(copied_experiment):
    _, case, path, saved = read_case(copied_experiment)
    graph, demand, cutoff, _ = analysis.specification(case["scenario"])
    data = run_simulation(graph, demand, memory_slots=case["capacity"], cutoff_time=cutoff,
                          horizon=case["horizon"], seed=case["seed"] + 100,
                          ticks_per_time_unit=1000000, admission_policy="reserved",
                          swap_policy=case["policy"]).to_dict()
    # Relabeling a valid trajectory does not make its random inputs matched.
    data["seed"] = case["seed"]
    saved["simulation"] = data
    saved["observed"] = analysis.observe_policy(data, warmup=case["warmup"])
    write_case(path, saved)
    with pytest.raises(ValueError, match="unmatched exogenous inputs"):
        analysis.build_report(copied_experiment)

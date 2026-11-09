"""Statistical reporting preserves independent runs, pairing, and uncertainty."""

import csv
import json
import math

import pytest

from scripts import statistical_analysis as stats


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def memory_data(tmp_path):
    directory = tmp_path / "memory"
    (directory / "runs").mkdir(parents=True)
    write_json(directory / "manifest.json", {
        "status": "complete", "failures": [], "warmup": 0,
        "sweep_settings": {"memory_slots": [4, None], "demand_factors": [1], "replicates": 3, "seed": 271},
        "configuration": {"simulation": {"horizon": 10, "swap_policy": "balancing",
                                          "admission_policy": "reserved", "cutoff_time": None},
                          "distillation_pairs": 1, "time_unit": "abstract"},
    })
    rows = []
    for budget, values in [(4, [1, 10, 20]), (None, [1.5, 10.5, 20.5])]:
        for replicate, value in enumerate(values):
            artifact = f"runs/{budget}-{replicate}.json"
            write_json(directory / artifact, {
                "status": "completed", "seed": 271 + replicate, "horizon": 10, "distillation_pairs": 1,
                "warmup": 0, "occupancy_by_node": [{"memory_slots": budget}],
                "completed_requests": int(value * 10), "throughput": value,
                "swap_policy": "balancing", "admission_policy": "reserved", "cutoff_time": None,
                "time_unit": "abstract",
            })
            rows.append({"demand_factor": 1, "memory_slots": "" if budget is None else budget,
                         "replicate": replicate, "seed": 271 + replicate, "status": "completed",
                         "throughput": value, "artifact": artifact})
    write_rows(directory / "simulation.csv", list(reversed(rows)))
    return directory


def test_mean_interval_uses_sample_variance_and_student_t():
    # Tabulated two-sided 95% t critical value for df=2; sample variance is 1.
    margin = 4.302652729911275 / math.sqrt(3)
    row = stats.summarize([1, 2, 3])
    assert row["mean"] == 2
    assert row["ci_low"] == pytest.approx(2 - margin)
    assert row["ci_high"] == pytest.approx(2 + margin)
    assert row["n"] == row["n_defined"] == 3


def test_undefined_observation_does_not_get_dropped():
    row = stats.summarize([1, None, 3])
    assert (row["n"], row["n_defined"], row["status"]) == (3, 2, "undefined_observations")
    assert row["mean"] is row["ci_low"] is row["ci_high"] is None


def test_single_run_reports_mean_without_confidence_interval():
    row = stats.summarize([7])
    assert row["mean"] == 7 and row["status"] == "single_run_no_ci"
    assert row["ci_low"] is row["ci_high"] is None


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")]])
def test_invalid_observations_fail(values):
    with pytest.raises(ValueError):
        stats.summarize(values)


def test_memory_pairing_uses_replicate_identity_despite_csv_order(memory_data):
    rows, seeds, count = stats.memory_statistics(memory_data)
    paired = next(row for row in rows if row["dynamics"] == "finite-minus-unlimited")
    assert count == 6
    assert [row["input_seed"] for row in seeds] == [271, 272, 273]
    assert (paired["mean"], paired["ci_low"], paired["ci_high"]) == (-0.5, -0.5, -0.5)
    assert next(row for row in rows if row["memory_slots"] is None)["ci_high"] > 20


@pytest.mark.parametrize("corruption,message", [
    ("missing", "missing memory runs"),
    ("duplicate", "duplicate memory run"),
    ("seed", "seed mismatch"),
    ("throughput", "throughput mismatch"),
    ("policy", "swap_policy mismatch"),
])
def test_incomplete_or_corrupt_memory_data_is_rejected(memory_data, corruption, message):
    path = memory_data / "simulation.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows.append(rows[0].copy())
    elif corruption == "seed":
        rows[0]["seed"] = rows[1]["seed"]
    else:
        raw_path = memory_data / rows[0]["artifact"]
        raw = stats.read_json(raw_path)
        if corruption == "policy":
            raw["swap_policy"] = "physical"
        else:
            raw["completed_requests"] += 1
        write_json(raw_path, raw)
    write_rows(path, rows)
    with pytest.raises(ValueError, match=message):
        stats.memory_statistics(memory_data)


def test_comparison_pairing_is_by_replicate_not_file_order(tmp_path, monkeypatch):
    directory = tmp_path / "comparison"
    (directory / "runs").mkdir(parents=True)
    (directory / "inputs").mkdir()
    write_json(directory / "manifest.json", {"replicates": 3, "distillation_pairs": [1], "horizon": 10, "seed": 271})
    # The separate verifier suite checks raw conservation. Here isolate pairing.
    monkeypatch.setattr(stats, "verify_directory", lambda _: {"validated_runs": 6})
    for replicate, value in enumerate([1, 100, 500]):
        write_json(directory / "inputs" / f"input-{replicate:03d}.json", {
            "metadata": {"graph_seed": replicate + 10}, "seed": replicate + 20, "stream_seeds": {},
        })
        for dynamics, increment in [("original", 0), ("corrected", 2)]:
            filename = f"{replicate if dynamics == 'original' else 2 - replicate}-{dynamics}.json"
            write_json(directory / "runs" / filename, {
                "replicate": replicate, "distillation_pairs": 1, "dynamics": dynamics,
                "total_pairs_consumed": value + increment, "legacy_overhead": 1,
                "corrected_overhead": 1, "minimum_completed_met": True,
            })
    rows, _, count = stats.comparison_statistics(directory)
    paired = next(row for row in rows if row["metric"] == "total_pairs_consumed"
                  and row["dynamics"] == "corrected-minus-original")
    assert count == 6
    assert (paired["mean"], paired["ci_low"], paired["ci_high"]) == (2, 2, 2)


def test_report_preserves_error_bars_and_unlimited_reference(memory_data, tmp_path, monkeypatch):
    from matplotlib.axes import Axes

    report = stats.build_report([], memory_data)
    report["comparison"] = [stats.summarize([1, 2, 3], experiment="synthetic", D=1, metric=metric,
                                           dynamics=dynamics)
                            for metric in ("total_pairs_consumed", "corrected_overhead")
                            for dynamics in ("original", "corrected")]
    calls = []
    original = Axes.errorbar

    def record(self, x, y, *args, **kwargs):
        calls.append((x, y, kwargs.get("yerr")))
        return original(self, x, y, *args, **kwargs)

    monkeypatch.setattr(Axes, "errorbar", record)
    output = stats.write_report(report, tmp_path / "report")
    assert len(calls) == 5 and all(error is not None for _, _, error in calls)
    reference = next(row for row in report["memory"] if row["memory_slots"] is None)
    x, y, errors = calls[-1]
    assert x[-1] == 1 and y[-1] == reference["mean"]
    assert errors[0][-1] == pytest.approx(reference["mean"] - reference["ci_low"])
    assert errors[1][-1] == pytest.approx(reference["ci_high"] - reference["mean"])
    for name in ("comparison_d1.png", "memory_throughput.png"):
        assert (output / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert stats.read_json(output / "statistics.json")["validated_memory_runs"] == 6
    with pytest.raises(ValueError, match="new or empty directory"):
        stats.write_report(report, output)

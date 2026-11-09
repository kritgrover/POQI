"""Sparse completions and censored first events must remain in the report."""

import csv
import json

import pytest

from scripts import scaling_analysis as scaling


def observation(first, horizon=10):
    return {"first_completion_step": first, "horizon": horizon,
            "total_pairs_consumed": int(first is not None), "finished": True,
            "stop_reason": "fixed_horizon", "minimum_completed_met": False,
            "corrected_overhead": None}


@pytest.mark.parametrize("successes,expected", [
    (0, (0, 0, .43448246478317476)),
    (5, (1, .5655175352168252, 1)),
    (2, (.4, .11762077423264783, .769275718723987))
])
def test_wilson_keeps_uncertainty_at_zero_and_all_successes(successes, expected):
    assert scaling.wilson(successes, 5) == pytest.approx(expected)


def test_all_censored_runs_are_retained():
    result = scaling.summarize_group([observation(None) for _ in range(5)])
    assert (result["n"], result["runs_with_completion"], result["censored_runs"]) == (5, 0, 5)
    assert result["completion_rate_mean"] == 0
    assert result["restricted_first_mean"] == 10
    assert result["completion_fraction_ci_high"] > .43
    assert scaling.first_observation(observation(None)) == {
        "first_completion_step": None, "observation_step": 10,
        "completion_observed": False, "right_censored": True}


def test_restricted_mean_includes_censored_times_not_only_successes():
    result = scaling.summarize_group([observation(2), *[observation(None) for _ in range(4)]])
    assert result["restricted_first_mean"] == 8.4
    assert result["restricted_first_ci_low"] == pytest.approx(8.4 - 2.7764451051977987 * 1.6)
    assert result["restricted_first_ci_high"] > 10  # Approximate interval is not silently clipped.
    assert result["completion_rate_mean"] == pytest.approx(.02)


@pytest.mark.parametrize("change,message", [
    ({"first_completion_step": -1}, "inconsistent"),
    ({"first_completion_step": 11}, "inconsistent"),
    ({"first_completion_step": None}, "inconsistent"),
    ({"first_completion_step": 1.5}, "inconsistent"),
    ({"finished": False}, "unfinished"),
])
def test_invalid_first_observations_are_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        scaling.first_observation({**observation(2), **change})


@pytest.fixture
def comparison(tmp_path):
    directory = tmp_path / "higher-d"
    (directory / "runs").mkdir(parents=True)
    (directory / "inputs").mkdir()
    (directory / "manifest.json").write_text(json.dumps({
        "status": "completed", "replicates": 5, "distillation_pairs": [2, 3], "horizon": 10, "seed": 271,
        "minimum_completed_requests": 100}))
    checkpoints = []
    for i in range(5):
        (directory / "inputs" / f"input-{i:03d}.json").write_text(json.dumps({
            "horizon": 10, "edges": [[0, 1, 20]], "generations": [[0, 1]] * 10,
            "seed": 100 + i, "metadata": {"graph_seed": 200 + i}}))
        for d in (2, 3):
            for dynamics in ("original", "corrected"):
                first = 2 if d == 3 and i == 0 else None
                count = int(first is not None)
                row = {**observation(first), "replicate": i, "distillation_pairs": d,
                       "dynamics": dynamics, "input_id": f"input-{i:03d}", "steps": 10,
                       "status": "insufficient_completions", "initial_inventory": 20,
                       "total_generated": 10, "total_swaps": 0, "remaining_inventory": 30 - d * count,
                       "completed_hops": {"1": count}, "completed_by_pair": [[0, 1, count]],
                       "final_inventory": [[0, 1, 30 - d * count]],
                       "corrected_denominator": 0, "legacy_denominator": 0, "legacy_overhead": None}
                (directory / "runs" / f"r{i:03d}-d{d}-{dynamics}.json").write_text(json.dumps(row))
                for horizon in (1, 10):
                    prefix_count = count if horizon == 10 else 0
                    checkpoints.append({"replicate": i, "distillation_pairs": d, "dynamics": dynamics,
                                        "step": horizon, "total_pairs_consumed": prefix_count,
                                        "total_generated": horizon, "total_swaps": 0,
                                        "remaining_inventory": 20 + horizon - d * prefix_count,
                                        "corrected_denominator": 0, "corrected_overhead": ""})
    with (directory / "checkpoints.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(checkpoints[0]))
        writer.writeheader()
        writer.writerows(checkpoints)
    return directory


def test_report_preserves_all_groups_and_censoring(comparison, tmp_path):
    report = scaling.build_report([comparison])
    assert report["validated_runs"] == len(report["observations"]) == 20
    assert len(report["summary"]) == 4
    assert all(row["n"] == 5 for row in report["summary"])
    assert sum(row["right_censored"] for row in report["observations"]) == 18
    assert all(row["undefined_overhead_runs"] == 5 for row in report["summary"])
    output = scaling.write_report(report, tmp_path / "report")
    assert (output / "scaling.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert json.loads((output / "scaling.json").read_text())["validated_runs"] == 20
    with pytest.raises(ValueError, match="new or empty"):
        scaling.write_report(report, output)


@pytest.mark.parametrize("corruption,expected", [("unmeasured", "missing first_completion_step"),
                                                 ("missing", "missing runs/partners"),
                                                 ("failed", "unfinished")])
def test_unmeasured_missing_or_failed_run_is_not_treated_as_censored(comparison, corruption, expected):
    path = comparison / "runs/r000-d2-original.json"
    if corruption == "missing":
        path.unlink()
    else:
        row = json.loads(path.read_text())
        if corruption == "unmeasured":
            row.pop("first_completion_step")
        else:
            row["finished"] = False
        path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match=expected):
        scaling.build_report([comparison])


def test_prefixes_reuse_trajectories_without_inflating_repetitions(comparison):
    report = scaling.build_report([comparison], horizons=[1, 10])
    assert report["validated_runs"] == 20
    assert len(report["summary"]) == 8 and len(report["observations"]) == 40
    assert all(row["n"] == 5 for row in report["summary"])
    early = [row for row in report["observations"] if row["horizon"] == 1]
    assert len(early) == 20 and all(row["right_censored"] for row in early)
    assert all(row["first_completion_step"] is None and row["observation_step"] == 1 for row in early)
    later = [row for row in report["summary"] if row["horizon"] == 10 and row["D"] == 3]
    assert all(row["restricted_first_mean"] == 8.4 for row in later)


@pytest.mark.parametrize("horizons", [[], [0], [10, 10], [11]])
def test_invalid_prefix_horizons_fail(comparison, horizons):
    with pytest.raises(ValueError, match="horizon"):
        scaling.build_report([comparison], horizons)


def test_missing_checkpoint_fails(comparison):
    path = comparison / "checkpoints.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], *lines[2:]]) + "\n")
    with pytest.raises(ValueError, match="missing checkpoint"):
        scaling.build_report([comparison], [1, 10])

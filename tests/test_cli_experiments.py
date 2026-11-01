"""Root interfaces and reproducible experiment artifacts, not performance claims."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from poqi.__main__ import main
from poqi.config import load_config, parse_config
from poqi.experiments.memory_sweep import run_memory_sweep
from poqi.reporting import ROOT, create_output


def test_supplied_configs_load():
    for path in (ROOT / "configs" / "memory").glob("*.json"):
        load_config(path)


@pytest.mark.parametrize("operation", ["solve", "min-generation", "size-memory"])
def test_lp_cli(operation, capsys):
    assert main(["lp", operation, "--config", str(ROOT / "configs/memory/chain.json")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"]
    if operation == "size-memory":
        assert data["memory_budget"] == pytest.approx(1.8)


def test_lp_only_does_not_import_sequence():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "import poqi.lp; import sys; assert 'sequence' not in sys.modules"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sweep_runs_matched_inputs_and_preserves_outputs(tmp_path):
    raw = deepcopy(load_config(ROOT / "configs/memory/direct.json").raw)
    raw["simulation"]["horizon"] = 10
    raw["sweep"] = {"memory_slots": [1, 2], "fractions": [0.9], "simulate": True, "replicates": 2}
    destination = tmp_path / "sweep"
    result = run_memory_sweep(parse_config(raw), destination)
    assert result["status"] == "complete"
    assert result["simulation_runs"] == 6  # Includes the unlimited policy baseline.
    first = json.loads((destination / "runs/simulation-0-0-0.json").read_text())
    second = json.loads((destination / "runs/simulation-0-1-0.json").read_text())
    assert first["offered_generation"] == second["offered_generation"]
    assert first["offered_requests"] == second["offered_requests"]
    assert first["lp_target_checks"][0]["proportional_target_met"] is not None
    original = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_memory_sweep(parse_config(raw), destination)
    assert (destination / "manifest.json").read_bytes() == original


def test_cutoff_targets_are_unmatched(tmp_path):
    raw = deepcopy(load_config(ROOT / "configs/memory/direct.json").raw)
    raw["simulation"].update(horizon=3, cutoff_time=1)
    raw["sweep"] = {"memory_slots": [1], "fractions": [0.9], "simulate": True, "replicates": 1}
    destination = tmp_path / "cutoff"
    run_memory_sweep(parse_config(raw), destination)
    data = json.loads((destination / "runs/simulation-0-0-0.json").read_text())
    assert data["lp_target_checks"][0]["proportional_target_met"] is None


def test_bad_sweep_creates_no_output(tmp_path):
    raw = deepcopy(load_config(ROOT / "configs/memory/direct.json").raw)
    raw["sweep"] = {"memory_slots": [1.5], "simulate": True}
    with pytest.raises(ValueError, match="integer"):
        run_memory_sweep(parse_config(raw), tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_cli_reports_failure_and_manifest(tmp_path, capsys):
    raw = deepcopy(load_config(ROOT / "configs/memory/direct.json").raw)
    raw["memory_slots"] = 0.5
    config = tmp_path / "fractional.json"
    config.write_text(json.dumps(raw))
    output = tmp_path / "bad-simulation"
    assert main(["simulate", "--config", str(config), "--output", str(output)]) == 1
    assert "integers" in capsys.readouterr().err
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("directory", ["SeQUeNCe", "quantum-network", ".git", ".venv", ".codex"])
def test_outputs_cannot_mutate_reserved_trees(directory):
    with pytest.raises(ValueError, match="cannot be written"):
        create_output(ROOT / directory / "forbidden-experiment")
    assert not (ROOT / directory / "forbidden-experiment").exists()


def test_sweep_failure_finalizes_manifest(tmp_path, monkeypatch):
    from poqi.experiments import memory_sweep
    def broken_solver(*args, **kwargs):
        raise RuntimeError("injected solver failure")
    monkeypatch.setattr(memory_sweep, "solve_throughput", broken_solver)
    output = tmp_path / "failed-sweep"
    with pytest.raises(RuntimeError, match="injected"):
        run_memory_sweep(load_config(ROOT / "configs/memory/direct.json"), output)
    data = json.loads((output / "manifest.json").read_text())
    assert data["status"] == "failed"
    assert "injected" in data["error"]


def test_simulation_invariant_failure_finalizes_manifest(tmp_path, monkeypatch, capsys):
    from poqi.simulation import sequence_adapter
    def broken_simulator(*args, **kwargs):
        raise AssertionError("injected conservation failure")
    monkeypatch.setattr(sequence_adapter, "run_simulation", broken_simulator)
    output = tmp_path / "failed-simulation"
    assert main(["simulate", "--config", str(ROOT / "configs/memory/direct.json"), "--output", str(output)]) == 1
    assert "conservation failure" in capsys.readouterr().err
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"

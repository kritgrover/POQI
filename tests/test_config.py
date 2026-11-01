from copy import deepcopy
import json

import pytest

from poqi.config import load_config, parse_config


@pytest.fixture
def config_data():
    return {
        "nodes": ["A", "B", "C"],
        "edges": [{"nodes": ["A", "B"], "generation_capacity": 1},
                  {"nodes": ["B", "C"], "generation_capacity": 2}],
        "demand_rate": [{"pair": ["C", "A"], "rate": 0.5}],
        "mean_residence_time": 1,
        "memory_slots": None,
        "time_unit": "abstract",
        "residence_time_source": "prescribed sensitivity coefficient",
        "demand_normalization": "Endpoint pair offered demand = 0.5; no normalization",
    }


def test_complete_config_preserves_types_and_input(config_data):
    config_data["mean_residence_time"] = [
        {"pair": ["B", "A"], "value": 1},
        {"pair": ["A", "C"], "value": 2},
        {"pair": ["B", "C"], "value": 3},
    ]
    config_data["memory_slots"] = [{"node": n, "slots": i + 0.5}
                                    for i, n in enumerate(config_data["nodes"])]
    original = deepcopy(config_data)
    result = parse_config(config_data)
    assert config_data == original
    assert result.demand_rate == {("A", "C"): 0.5}
    assert result.mean_residence_time[("A", "C")] == 2
    assert result.memory_slots == {"A": 0.5, "B": 1.5, "C": 2.5}
    assert result.graph["B"]["C"]["generation_capacity"] == 2
    assert result.lp_kwargs() == {
        "mean_residence_time": result.mean_residence_time,
        "memory_slots": result.memory_slots,
        "distillation_pairs": 1, "balance_mode": "stationary",
    }


def test_explicit_unlimited_and_mixed_node_labels(config_data):
    config_data["nodes"] = [1, "1"]
    config_data["edges"] = [{"nodes": ["1", 1], "generation_capacity": 2}]
    config_data["demand_rate"] = [{"pair": ["1", 1], "rate": 1}]
    parsed = parse_config(config_data)
    assert parsed.memory_slots is None
    assert parsed.demand_rate == {(1, "1"): 1}
    del config_data["memory_slots"]
    with pytest.raises(ValueError, match="Missing.*memory_slots"):
        parse_config(config_data)


@pytest.mark.parametrize("field,value", [
    ("mean_residence_time", 0), ("mean_residence_time", True),
    ("mean_residence_time", float("nan")), ("mean_residence_time", float("inf")),
    ("memory_slots", -1), ("memory_slots", False),
    ("time_unit", " "), ("residence_time_source", ""),
    ("distillation_pairs", 0), ("distillation_pairs", 1.5),
    ("distillation_pairs", True), ("balance_mode", "expiry"),
    ("nodes", [1, True]), ("nodes", ["A", "A"]),
    ("demand_rate", []), ("sweep", []),
])
def test_invalid_scalar_configuration(config_data, field, value):
    config_data[field] = value
    with pytest.raises(ValueError):
        parse_config(config_data)


@pytest.mark.parametrize("section,record", [
    ("edges", {"nodes": ["B", "A"], "generation_capacity": 1}),
    ("demand_rate", {"pair": ["A", "C"], "rate": 1}),
])
def test_duplicate_reversed_pairs(config_data, section, record):
    config_data[section].append(record)
    with pytest.raises(ValueError, match="Duplicate unordered"):
        parse_config(config_data)


@pytest.mark.parametrize("pair", [["A", "A"], ["A", "unknown"], ["A"], ["A", True]])
def test_invalid_pairs(config_data, pair):
    config_data["demand_rate"][0]["pair"] = pair
    with pytest.raises(ValueError):
        parse_config(config_data)


def test_complete_tau_and_memory_required(config_data):
    config_data["mean_residence_time"] = [{"pair": ["A", "B"], "value": 1}]
    with pytest.raises(ValueError, match="every unordered pair"):
        parse_config(config_data)
    config_data["mean_residence_time"] = 1
    config_data["memory_slots"] = [{"node": "A", "slots": 1}]
    with pytest.raises(ValueError, match="every node"):
        parse_config(config_data)


def test_unknown_keys_and_generation_capacity(config_data):
    config_data["typo"] = 1
    with pytest.raises(ValueError, match="Unknown configuration"):
        parse_config(config_data)
    del config_data["typo"]
    config_data["edges"][0]["capacity"] = config_data["edges"][0].pop("generation_capacity")
    with pytest.raises(ValueError, match="edge"):
        parse_config(config_data)


def test_simulation_initial_age_is_not_mean_residence(config_data):
    config_data["simulation"] = {
        "horizon": 10, "seed": 271, "cutoff_time": 5,
        "swap_policy": "balancing", "admission_policy": "reserved",
        "request_regime": "offered",
        "initial_pairs": [{"endpoints": ["A", "B"], "count": 1, "age": 0}],
    }
    parsed = parse_config(config_data)
    assert parsed.mean_residence_time == 1
    assert parsed.simulation["initial_pairs"][0]["age"] == 0
    config_data["simulation"]["initial_pairs"][0]["age"] = 2
    with pytest.raises(ValueError, match="age=0"):
        parse_config(config_data)


@pytest.mark.parametrize("options", [
    {"horizon": 0}, {"seed": -1}, {"ticks_per_time_unit": 0},
    {"cutoff_time": -1}, {"swap_policy": "perfect"}, {"request_regime": "saturated"},
    {"record_events": 1}, {"unknown": 1},
    {"initial_pairs": [{"endpoints": ["A", "C"], "count": 1}]},
    {"trace": [{"time": 0, "kind": "swap", "endpoints": ["A", "C"], "pivot": "A"}]},
    {"trace": [{"time": 0, "kind": "generate", "endpoints": ["A", "C"]}]},
    {"trace": [{"time": 0, "kind": "request", "endpoints": ["A", "B"]}]},
])
def test_invalid_simulation_options(config_data, options):
    config_data["simulation"] = options
    with pytest.raises(ValueError):
        parse_config(config_data)


def test_load_config_and_reject_ambiguous_json(tmp_path, config_data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data), encoding="utf-8")
    assert load_config(path).demand_rate == {("A", "C"): 0.5}
    path.write_text('{"nodes": [0,1], "nodes": [1,2]}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON"):
        load_config(path)
    path.write_text('{"mean_residence_time": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite JSON"):
        load_config(path)

"""Validated JSON configuration shared by the root LP and simulation runners.

JSON pair and node mappings use records, so integer and string node labels are
preserved and duplicate reversed pairs cannot disappear during deserialization.
``memory_slots: null`` is the explicit unlimited-memory mode.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any

import networkx as nx


@dataclass(frozen=True)
class Config:
    graph: nx.Graph
    demand_rate: dict
    mean_residence_time: float | dict
    memory_slots: float | dict | None
    distillation_pairs: int
    balance_mode: str
    time_unit: str
    residence_time_source: str
    simulation: dict
    sweep: dict
    raw: dict

    def lp_kwargs(self) -> dict:
        return {
            "mean_residence_time": self.mean_residence_time,
            "memory_slots": self.memory_slots,
            "distillation_pairs": self.distillation_pairs,
            "balance_mode": self.balance_mode,
        }


def _object(value: Any, label: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ValueError(f"Unknown {label} keys: {sorted(unknown, key=str)}")
    if missing:
        raise ValueError(f"Missing {label} keys: {sorted(missing)}")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        sign = "positive" if positive else "nonnegative"
        raise ValueError(f"{label} must be finite and {sign}")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _records(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of records")
    return value


def parse_config(data: dict) -> Config:
    """Parse a configuration without mutating the supplied dictionary.

    Residence times are prescribed coefficients, independent of a simulator's
    cutoff. Every unordered pair needs a coefficient even when it is a nonedge.
    Fractional memory is valid for the LP; the hard-slot simulator subsequently
    requires integer budgets.
    """
    required = {
        "nodes", "edges", "demand_rate", "mean_residence_time", "memory_slots",
        "time_unit", "residence_time_source", "demand_normalization",
    }
    allowed = required | {"distillation_pairs", "balance_mode", "simulation", "sweep"}
    _object(data, "configuration", allowed, required)
    nodes = data["nodes"]
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise ValueError("nodes must be a list containing at least two nodes")
    if any(isinstance(node, bool) or not isinstance(node, (str, int)) for node in nodes):
        raise ValueError("Node labels must be strings or integers, not booleans")
    if len(set(nodes)) != len(nodes):
        raise ValueError("nodes contains duplicate labels")
    ranks = {node: i for i, node in enumerate(nodes)}

    def canonical(value, label):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{label} must contain exactly two endpoints")
        u, v = value
        if any(isinstance(node, bool) or not isinstance(node, (str, int)) for node in value):
            raise ValueError(f"{label} has an invalid node label")
        if u not in ranks or v not in ranks or u == v:
            raise ValueError(f"{label} contains unknown nodes or is a self-pair: {value!r}")
        return (u, v) if ranks[u] < ranks[v] else (v, u)

    def pair_values(value, label, key, *, positive=False, complete=False):
        output = {}
        for row in _records(value, label):
            _object(row, label + " record", {"pair", key}, {"pair", key})
            pair = canonical(row["pair"], label)
            if pair in output:
                raise ValueError(f"Duplicate unordered pair in {label}: {pair!r}")
            output[pair] = _number(row[key], label + "." + key, positive=positive)
        if complete and set(output) != set(combinations(nodes, 2)):
            raise ValueError(f"{label} must specify every unordered pair, including nonedges")
        return output

    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    for row in _records(data["edges"], "edges"):
        _object(row, "edge", {"nodes", "generation_capacity"}, {"nodes", "generation_capacity"})
        pair = canonical(row["nodes"], "edge")
        if graph.has_edge(*pair):
            raise ValueError(f"Duplicate unordered generation edge: {pair!r}")
        graph.add_edge(*pair, generation_capacity=_number(row["generation_capacity"], "generation_capacity"))
    demand = pair_values(data["demand_rate"], "demand_rate", "rate")
    if not demand or sum(demand.values()) <= 0:
        raise ValueError("demand_rate must contain positive total offered demand")
    tau_raw = data["mean_residence_time"]
    tau = (pair_values(tau_raw, "mean_residence_time", "value", positive=True, complete=True)
           if isinstance(tau_raw, list)
           else _number(tau_raw, "mean_residence_time", positive=True))
    memory_raw = data["memory_slots"]
    if memory_raw is None:
        memory = None
    elif isinstance(memory_raw, list):
        memory = {}
        for row in memory_raw:
            _object(row, "memory_slots record", {"node", "slots"}, {"node", "slots"})
            node = row["node"]
            if isinstance(node, bool) or not isinstance(node, (str, int)) or node not in ranks:
                raise ValueError(f"Unknown memory_slots node: {node!r}")
            if node in memory:
                raise ValueError(f"Duplicate memory_slots node: {node!r}")
            memory[node] = _number(row["slots"], "memory_slots.slots")
        if set(memory) != set(nodes):
            raise ValueError("memory_slots must specify every node, or use null for unlimited memory")
    else:
        memory = _number(memory_raw, "memory_slots")
    distillation = _integer(data.get("distillation_pairs", 1), "distillation_pairs", minimum=1)
    balance = data.get("balance_mode", "stationary")
    if balance not in ("stationary", "legacy"):
        raise ValueError("balance_mode must be 'stationary' or 'legacy'")
    time_unit = _text(data["time_unit"], "time_unit")
    source = _text(data["residence_time_source"], "residence_time_source")
    if "demand_normalization" in data:
        _text(data["demand_normalization"], "demand_normalization")

    sim = deepcopy(data.get("simulation", {}))
    sim_keys = {"horizon", "seed", "ticks_per_time_unit", "cutoff_time", "swap_policy",
                "admission_policy", "request_regime", "initial_pairs", "trace", "record_events"}
    _object(sim, "simulation", sim_keys)
    if "horizon" in sim:
        sim["horizon"] = _number(sim["horizon"], "simulation.horizon", positive=True)
    if "seed" in sim:
        sim["seed"] = _integer(sim["seed"], "simulation.seed")
    if "ticks_per_time_unit" in sim:
        sim["ticks_per_time_unit"] = _integer(sim["ticks_per_time_unit"], "simulation.ticks_per_time_unit", minimum=1)
    if sim.get("cutoff_time") is not None:
        sim["cutoff_time"] = _number(sim["cutoff_time"], "simulation.cutoff_time", positive=True)
    for key, choices in {
        "swap_policy": ("balancing", "physical", "none"),
        "admission_policy": ("reserved", "tail_drop"),
        "request_regime": ("offered",),
    }.items():
        if key in sim and sim[key] not in choices:
            raise ValueError(f"simulation.{key} must be one of {choices}")
    if "record_events" in sim and not isinstance(sim["record_events"], bool):
        raise ValueError("simulation.record_events must be boolean")
    if sim.get("initial_pairs") is not None:
        seen = set()
        for row in _records(sim["initial_pairs"], "simulation.initial_pairs"):
            _object(row, "initial_pairs record", {"endpoints", "count", "age"}, {"endpoints", "count"})
            pair = canonical(row["endpoints"], "initial_pairs")
            if pair in seen:
                raise ValueError(f"Duplicate unordered initial_pairs pair: {pair!r}")
            seen.add(pair)
            if not graph.has_edge(*pair):
                raise ValueError("initial_pairs must occupy physical generation edges")
            row["count"] = _integer(row["count"], "initial_pairs.count")
            row["age"] = _number(row.get("age", 0), "initial_pairs.age")
            if row["age"] != 0:
                raise ValueError("initial_pairs currently require age=0")
    if sim.get("trace") is not None:
        for row in _records(sim["trace"], "simulation.trace"):
            _object(row, "trace event", {"time", "kind", "endpoints", "pivot", "count"},
                    {"time", "kind", "endpoints"})
            row["time"] = _number(row["time"], "trace.time")
            kind = row["kind"]
            if kind not in ("generate", "request", "swap"):
                raise ValueError("trace.kind must be 'generate', 'request', or 'swap'")
            pair = canonical(row["endpoints"], "trace.endpoints")
            if kind == "generate" and not graph.has_edge(*pair):
                raise ValueError("trace generation must use a physical edge")
            if kind == "request" and pair not in demand:
                raise ValueError("trace request pair must be declared in demand_rate")
            if "count" in row:
                row["count"] = _integer(row["count"], "trace.count", minimum=1)
            if kind == "swap":
                pivot = row.get("pivot")
                if (isinstance(pivot, bool) or not isinstance(pivot, (str, int))
                        or pivot not in ranks or pivot in pair):
                    raise ValueError("trace swap requires a known pivot distinct from both endpoints")
            elif "pivot" in row:
                raise ValueError("Only trace swap events may specify a pivot")
    sweep = deepcopy(data.get("sweep", {}))
    if not isinstance(sweep, dict):
        raise ValueError("sweep must be an object")
    return Config(graph, demand, tau, memory, distillation, balance, time_unit,
                  source, sim, sweep, deepcopy(data))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def load_config(path: str | Path) -> Config:
    """Load strict JSON, rejecting duplicate object keys and nonfinite constants."""
    def invalid_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    with Path(path).open(encoding="utf-8-sig") as handle:
        data = json.load(handle, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    return parse_config(data)

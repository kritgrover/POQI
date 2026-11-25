"""Check the offered-load, two-slot pressure chain against the public simulator."""

import argparse
from collections import deque
import json
from pathlib import Path

import networkx as nx

from poqi.simulation import run_simulation


EVENTS = {"L": ("generate", (0, 1)), "R": ("generate", (1, 2)), "A": ("request", (0, 2))}
# Each pair is encoded by its endpoints and the physical origin at each endpoint.
LEFT = ((0, 1), (1, 0))
RIGHT = ((1, 2), (2, 1))
VIRTUAL = ((0, 2), (1, 1))
REVERSED_LEFT = ((0, 1), (1, 2))
REVERSED_RIGHT = ((1, 2), (0, 1))
INVENTORIES = {
    (): "empty", (LEFT,): "left", (RIGHT,): "right", (VIRTUAL,): "virtual",
    (REVERSED_LEFT,): "poison_left", (REVERSED_RIGHT,): "poison_right",
    tuple(sorted((REVERSED_LEFT, LEFT))): "trap_left",
    tuple(sorted((REVERSED_RIGHT, RIGHT))): "trap_right",
}


def simulate_word(word, *, policy="pressure_relaxed"):
    """Submit one event per tick, preserving physical lineage from an empty start."""
    graph = nx.path_graph(3)
    nx.set_edge_attributes(graph, 1, "generation_capacity")
    trace = []
    for tick, symbol in enumerate(word, 1):
        kind, endpoints = EVENTS[symbol]
        trace.append({"kind": kind, "endpoints": endpoints, "time": tick})
    return run_simulation(graph, {(0, 2): 1}, trace=trace, memory_slots=2,
                          swap_policy=policy, ticks_per_time_unit=1,
                          horizon=len(word) + 1)


def replay(word):
    result = simulate_word(word)
    pairs = []
    for pair in result["live_pairs"]:
        endpoints = tuple(pair["endpoints"])
        origins = {entry["node"]: entry["neighbor"] for entry in pair["origins"]}
        pairs.append((endpoints, tuple(origins[node] for node in endpoints)))
    inventory = INVENTORIES[tuple(sorted(pairs))]
    return (inventory, result["unserved_requests"]), result["completed_requests"]


def predicted_transition(state, event):
    inventory, queue = state
    if event == "A":
        if inventory == "virtual":
            return ("empty", 0), 1
        return (inventory, queue + 1), 0
    side = "left" if event == "L" else "right"
    if inventory == "empty":
        return (side, queue), 0
    if inventory == "virtual":
        opposite = "right" if side == "left" else "left"
        return ("poison_" + opposite, 0), 0
    if inventory in {"left", "right"} and side != inventory:
        if queue:
            return ("empty", queue - 1), 1
        return ("virtual", 0), 0
    if inventory == "poison_" + side:
        return ("trap_" + side, queue), 0
    return state, 0


def check_transitions():
    # Queue counts above one differ only in how many requests remain after a
    # completion. Include counts two and three as distinct representatives.
    initial = ("empty", 0)
    paths = {initial: ""}
    pending = deque([initial])
    checked = 0
    while pending:
        state = pending.popleft()
        word = paths[state]
        source, previous = replay(word)
        if source != state:
            raise ValueError(f"wrong source state after {word!r}: {source}")
        for symbol in EVENTS:
            word_next = word + symbol
            target, completed = replay(word_next)
            observation = (target, completed - previous)
            if observation != predicted_transition(state, symbol):
                raise ValueError(f"incorrect transition after {word_next!r}: {observation}")
            checked += 1
            if target[1] <= 3 and target not in paths:
                paths[target] = word_next
                pending.append(target)
    expected = {(inventory, queue) for inventory in INVENTORIES.values() for queue in range(4)
                if inventory != "virtual" or queue == 0}
    if set(paths) != expected:
        raise ValueError(f"incorrect reachable states: {set(paths) ^ expected}")
    return {"states": len(paths), "transitions": checked,
            "witnesses": [{"inventory": inventory, "backlog": queue, "events": word}
                          for (inventory, queue), word in sorted(paths.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional new JSON report")
    args = parser.parse_args()
    report = check_transitions()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(f"Checked {report['transitions']} transitions over {report['states']} inventory/backlog states.")


if __name__ == "__main__":
    main()

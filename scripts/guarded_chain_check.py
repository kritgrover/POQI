"""Check the orientation-guarded two-slot theorem against SeQUeNCe event traces."""

import argparse
from collections import deque
import json
from pathlib import Path

if __package__:
    from .saturated_chain_check import check_case, reachable_transitions
    from .two_slot_chain_check import EVENTS, LEFT, RIGHT, VIRTUAL, simulate_word
else:
    from saturated_chain_check import check_case, reachable_transitions
    from two_slot_chain_check import EVENTS, LEFT, RIGHT, VIRTUAL, simulate_word


# Triples give the destination inventory after left generation, right generation,
# or a request, respectively. The final entry gives completions on that request.
# A cached V suppresses a second center swap even when L and R are both present.
IDLE = {
    "empty": ("L", "R", "empty", 0),
    "L": ("L", "V", "L", 0),
    "R": ("V", "R", "R", 0),
    "V": ("LV", "RV", "empty", 1),
    "LV": ("LV", "LRV", "L", 1),
    "RV": ("LRV", "RV", "R", 1),
    "LRV": ("LRV", "LRV", "LR", 1),
    "LR": ("V", "V", "empty", 1),
}
BUSY_PHASES = ("empty", "L", "R")
SYMBOL = {LEFT: "L", RIGHT: "R", VIRTUAL: "V"}


def predicted_transition(state, symbol):
    phase, pending = state
    if pending == 0:
        left, right, request, consumed = IDLE[phase]
        if symbol == "A":
            return (request, 1 - consumed), consumed
        return (left if symbol == "L" else right, 0), 0
    if symbol == "A":
        return (phase, pending + 1), 0
    if phase == "empty" or symbol == phase:
        return (symbol, pending), 0
    return ("empty", pending - 1), 1


def replay(word):
    result = simulate_word(word, policy="pressure_oriented")
    pairs = []
    for pair in result["live_pairs"]:
        endpoints = tuple(pair["endpoints"])
        origins = {entry["node"]: entry["neighbor"] for entry in pair["origins"]}
        signature = (endpoints, tuple(origins[node] for node in endpoints))
        pairs.append(SYMBOL[signature])
    if any(event["pivot"] != 1 for event in result["events"] if event["kind"] == "swap"):
        raise ValueError(f"guard allowed an endpoint swap after {word!r}")
    phase = "".join(sorted(pairs)) or "empty"
    return (phase, result["unserved_requests"]), result["completed_requests"]


def check_transitions():
    initial = ("empty", 0)
    witnesses = {initial: ("", 0)}
    pending = deque([initial])
    checked = 0
    while pending:
        state = pending.popleft()
        word, previous_count = witnesses[state]
        for symbol in EVENTS:
            next_word = word + symbol
            target, count = replay(next_word)
            observation = (target, count - previous_count)
            if observation != predicted_transition(state, symbol):
                raise ValueError(f"unexpected transition after {next_word!r}: {observation}")
            checked += 1
            if target not in witnesses and target[1] <= 3:
                witnesses[target] = (next_word, count)
                pending.append(target)
    expected = {(phase, 0) for phase in IDLE}
    expected.update((phase, queue) for queue in (1, 2, 3) for phase in BUSY_PHASES)
    if set(witnesses) != expected:
        raise ValueError(f"reachable inventories disagree: {set(witnesses) ^ expected}")
    return {"states": len(witnesses), "transitions": checked,
            "witnesses": [{"phase": phase, "queue": queue, "events": word}
                          for (phase, queue), (word, _) in sorted(witnesses.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional fresh JSON file")
    args = parser.parse_args()
    offered = check_transitions()
    # This recovers the saturated service rate directly from the simulator's
    # joint inventory states at each of three link-rate settings.
    saturated = check_case(2, "pressure_oriented")
    parity = []
    for budget in range(1, 17):
        ordinary = reachable_transitions(budget, "pressure_relaxed")
        guarded = reachable_transitions(budget, "pressure_oriented")
        if ordinary != guarded:
            raise ValueError(f"saturated transitions differ at {budget} slots")
        parity.append({"memory": budget, "transitions": 2 * len(ordinary)})
    report = {"offered": offered, "saturated": saturated, "saturated_policy_parity": parity}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(f"Checked {offered['transitions']} offered transitions and "
          f"{len(saturated['rates_checked'])} saturated service rates. "
          f"Matched {sum(row['transitions'] for row in parity)} saturated transitions.")


if __name__ == "__main__":
    main()

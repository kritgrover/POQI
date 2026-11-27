import ast
import hashlib
import json
import os
from pathlib import Path
import random
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.srs_protocol import SlottedProtocol


CHAIN = ((0, 1), (1, 2), (2, 3))


def protocol(edges=CHAIN, slots=2, policy="srs", cutoff=8, max_length=3, **kwargs):
    return SlottedProtocol(edges, slots, policy=policy, cutoff=cutoff, max_length=max_length,
                           seed=123, **kwargs)


def outcomes(edges, successful):
    return {edge: edge in successful for edge in edges}


def test_adjacent_srs_measurements_compose_in_one_slot_with_inherited_cutoff_and_length():
    sim = protocol()
    sim.step(0, outcomes(CHAIN, [CHAIN[0]]))
    sim.step(1, outcomes(CHAIN, CHAIN[1:]))
    assert sim.counters["swaps"] == 2
    (output,) = sim.backend.links.values()
    assert {a[0] for a in output.ends} == {0, 3}
    assert (output.born, output.segments) == (0, 3)
    for tick in range(2, 9):
        sim.step(tick, outcomes(CHAIN, []))
    assert not sim.backend.links
    assert sim.counters["expired"] == 1


def test_length_limit_is_enforced_before_queued_consumption():
    sim = protocol(max_length=2)
    assert sim.step(0, outcomes(CHAIN, CHAIN), [(0, 3)]) == []
    assert sim.counters["over_length"] == 1
    assert sim.pending == 1


def test_srs_failure_consumes_inputs_and_invalidates_composed_output():
    sim = protocol(swap_success=0)
    sim.step(0, outcomes(CHAIN, CHAIN))
    assert sim.counters["swaps"] == 2
    assert not sim.counters["swap_successes"]
    assert not sim.backend.links


def test_srs_closed_cycle_competing_swaps_consume_all_physical_qubits():
    edges = ((0, 1), (1, 2), (2, 3), (0, 3))
    sim = protocol(edges)
    sim.step(0, outcomes(edges, edges))
    assert sim.counters["swaps"] == 4
    assert not sim.backend.at


def test_srs_rejects_physically_adjacent_remote_partners_and_respects_one_swap_per_pivot():
    triangle = ((0, 1), (1, 2), (0, 2))
    sim = protocol(triangle)
    sim.step(0, outcomes(triangle, triangle))
    assert sim.counters["swaps"] == 0
    star = ((0, 1), (0, 2), (0, 3), (0, 4))
    sim = protocol(star, slots=4)
    sim.step(0, outcomes(star, star))
    assert sim.counters["swaps"] == 1


@pytest.mark.parametrize("policy", ["srs", "pressure_oriented", "pressure_pre_drop", "pressure_post_drop"])
def test_request_survives_empty_slot_and_is_served_fifo(policy):
    edges = ((0, 1),)
    sim = protocol(edges, policy=policy)
    assert sim.step(0, outcomes(edges, []), [(1, 0)]) == []
    assert sim.step(1, outcomes(edges, edges), [(0, 1)]) == [((0, 1), 0)]
    assert sim.step(2, outcomes(edges, edges)) == [((0, 1), 1)]
    assert sim.pending == 0


def test_pre_attempt_eviction_can_waste_a_pair_when_generation_fails():
    # The first slot produces a virtual pair that occupies both end registers.
    # The next slot's left-link attempt fails after pre-eviction.
    edges = ((0, 1), (1, 2))
    sims = [protocol(edges, slots={0: 1, 1: 2, 2: 1}, policy=p)
            for p in ("pressure_pre_drop", "pressure_post_drop")]
    for sim in sims:
        sim.step(0, outcomes(edges, edges))
    pre, post = (sim.step(1, outcomes(edges, []), [(0, 2)]) for sim in sims)
    assert pre == [] and post == [((0, 2), 1)]
    assert [s.counters["dropped"] for s in sims] == [1, 0]
    assert [s.counters["attempts"] for s in sims] == [4, 4]


def test_pre_and_post_eviction_are_identical_with_successful_generations():
    edges = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 4))
    sims = [protocol(edges, policy=p, swap_success=0.6) for p in ("pressure_pre_drop", "pressure_post_drop")]
    for tick in range(30):
        arrivals = [(0, 2)] if tick % 3 == 0 else []
        supplied = outcomes(edges, edges)
        assert sims[0].step(tick, supplied, arrivals) == sims[1].step(tick, supplied, arrivals)
    assert sims[0].counters == sims[1].counters
    assert sims[0].counters["dropped"] > 0


def _authors_driver(source, nodes, edges, slots, seed, q_swap, p_swap, cutoff, max_length):
    """Replay the pinned main_cd.py without its notebook and plotting imports."""
    names = {"advance_time", "cutoffs", "generate_all_links", "swap", "remove_long_links",
             "step_protocol_srs", "create_qubit_registers"}
    source_text = Path(source).read_text(encoding="utf-8")
    assert hashlib.sha256(source_text.encode()).hexdigest() == "f201e5b768f47eeaabab54faaf997ed3f17c24477cb1a80f45068e2665254e0b"
    module = ast.parse(source_text)
    module.body = [f for f in module.body if isinstance(f, ast.FunctionDef) and f.name in names]
    choices = random.Random(seed)

    def permute(seq):
        shuffled = list(seq)
        choices.shuffle(shuffled)
        return shuffled

    native_random = SimpleNamespace(rand=choices.random, permutation=permute)
    namespace = {"random": choices,
                 "np": SimpleNamespace(random=native_random, zeros=np.zeros, arange=np.arange, inf=np.inf)}
    exec(compile(module, str(source), "exec"), namespace)
    adjacency = np.zeros((nodes, nodes))
    for u, v in edges:
        adjacency[u, v] = adjacency[v, u] = 1
    state = namespace["create_qubit_registers"](adjacency, slots // 2)
    generate = namespace["generate_all_links"]
    # Both simulations use zero offered requests in this parity check.
    namespace["consume_fixed_rate"] = lambda state, rate: state

    def step(tick, outcomes):
        def generate_with_common_heralds(registers, probability):
            heralds = iter(outcomes[u, v] for u, v in sorted(edges)
                           if None in registers[u][v] and None in registers[v][u])
            native_random.rand = lambda: 0.0 if next(heralds) else 1.0
            try:
                return generate(registers, probability)
            finally:
                native_random.rand = choices.random

        namespace["generate_all_links"] = generate_with_common_heralds
        namespace["step_protocol_srs"](state, 0.5, q_swap, p_swap, 0, cutoff, max_length)
        physical = []
        for u, row in enumerate(state):
            for v, register in enumerate(row):
                if register == 0:
                    continue
                for i, stored in enumerate(register):
                    if stored is not None:
                        age, swaps, remote = stored
                        local = (u, v, i)
                        remote = tuple(int(x) for x in remote)
                        if local < remote:
                            physical.append((local, remote, age, swaps + 1))
        return sorted(physical)

    return step


def _slotted_trace(nodes, q_swap, p_swap, source=None):
    slots, cutoff, max_length, seed = 4, 7, nodes - 1, 8051
    edges = sorted([(i, i + 1) for i in range(nodes - 1)] + [(0, nodes - 1)])
    heralds = random.Random(1964)
    if source:
        step = _authors_driver(source, nodes, edges, slots, seed, q_swap, p_swap, cutoff, max_length)
    else:
        sim = SlottedProtocol(edges, slots, seed=seed, cutoff=cutoff, max_length=max_length,
                              policy="srs", swap_attempt=q_swap, swap_success=p_swap)

        def step(tick, outcomes):
            sim.step(tick, outcomes)
            return sorted((*sorted(link.ends), tick - link.born, link.segments)
                          for link in sim.backend.links.values())

    trace = []
    for tick in range(96):
        outcomes = {edge: heralds.random() < 0.64 for edge in edges}
        trace.append(step(tick, outcomes))
    return hashlib.sha256(json.dumps(trace, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("nodes,q_swap,p_swap,expected", [
    (6, 0., 1., "7c4441d0675f26cecd178eb6080a2621440855cf9e152c14df665d70e919cf4a"),
    (6, .5, .8, "594ecc60b53c7bffe18c13913d195ed3d310f52eb16c85e54ebde43f81e35324"),
    (8, 1., 1., "ecb4e59f6337678b2a3b1f10795108844830eca15414c15b4a846ce987943ce7"),
])
def test_pinned_authors_physical_register_trace(nodes, q_swap, p_swap, expected):
    # Set SRS_UPSTREAM_SOURCE to the authors' pinned main_cd.py to also regenerate
    # the golden trace. Values capture every surviving address, age and length
    # at the end of every slot, including simultaneous swaps and inherited loss.
    assert _slotted_trace(nodes, q_swap, p_swap) == expected
    if source := os.environ.get("SRS_UPSTREAM_SOURCE"):
        assert _slotted_trace(nodes, q_swap, p_swap, source) == expected

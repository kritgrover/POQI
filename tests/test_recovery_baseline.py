"""Drop-when-stuck recovery, service-continuity metrics and shared-pool lockups."""

import networkx as nx
import pytest

from poqi.config import parse_config
from poqi.simulation import run_simulation
from poqi.simulation.inventory import Inventory
from scripts.dead_state_search import Arm, TOPOLOGIES, analyse, check_against_simulator
from scripts import recovery_baseline


def graph(nodes=3):
    result = nx.path_graph(nodes)
    nx.set_edge_attributes(result, 1.0, "generation_capacity")
    return result


def event(time, kind, endpoints, count=1):
    return {"time": time, "kind": kind, "endpoints": endpoints, "count": count}


def simulate(trace, *, nodes=3, demand=None, horizon=20, **kwargs):
    return run_simulation(graph(nodes), {(0, nodes - 1): 1.0} if demand is None else demand,
                          horizon=horizon, ticks_per_time_unit=100, trace=trace, **kwargs).to_dict()


# The two-slot chain trap: a cached end-to-end pair is swapped backward at node 2,
# and the result holds the center's only slot toward node 2.
TRAP = [event(1, "generate", [0, 1]), event(2, "generate", [1, 2]), event(3, "generate", [1, 2]),
        event(4, "generate", [0, 1]), event(5, "request", [0, 2])]


def test_the_trace_reaches_the_trap_and_nothing_releases_it_without_recovery():
    result = simulate(TRAP + [event(t, "generate", [1, 2]) for t in (6, 9, 12)],
                      memory_slots=2, swap_policy="pressure_relaxed")
    assert result["completed_requests"] == 0
    # The center is full: its slot toward 0 holds an elementary pair, its slot toward 2 the trap.
    assert result["rejections_by_reason"] == {"hard_slots": 3}
    assert sorted(tuple(item["endpoints"]) for item in result["live_pairs"]) == [(0, 1), (0, 1)]
    assert result["recovery_policy"] == "none" and "stuck_drops" not in result


def test_zero_patience_drop_releases_the_trap_at_the_next_blocked_generation():
    result = simulate(TRAP + [event(6, "generate", [1, 2])], memory_slots=2,
                      swap_policy="pressure_relaxed", recovery_policy="drop_when_stuck")
    assert result["stuck_drops"] == 1 and result["stuck_drop_events"] == 1
    assert result["completed_requests"] == 1
    assert result["admission_rejections"] == 0
    drop = next(e for e in result["events"] if e["kind"] == "drop")
    assert drop["time"] == 6 and drop["blocked_by"] == "hard_slots"


def test_patience_delays_the_drop_until_the_blocker_has_been_stored_that_long():
    # The wrong-origin pair is created by the swap at time 3.
    kwargs = dict(memory_slots=2, swap_policy="pressure_relaxed", recovery_policy="drop_when_stuck",
                  stuck_patience=5)
    early = simulate(TRAP + [event(7.99, "generate", [1, 2])], **kwargs)
    assert early["stuck_drops"] == 0 and early["completed_requests"] == 0
    late = simulate(TRAP + [event(7.99, "generate", [1, 2]), event(8, "generate", [1, 2])], **kwargs)
    assert late["stuck_drops"] == 1 and late["completed_requests"] == 1
    assert late["admission_rejections"] == 1


def test_an_ordinary_full_link_is_rejected_and_never_dropped():
    result = simulate([event(1, "generate", [0, 1], 5)], memory_slots=2,
                      swap_policy="pressure_relaxed", recovery_policy="drop_when_stuck")
    assert result["stuck_drops"] == 0
    assert result["rejections_by_reason"] == {"neighbor_reservation": 4}


def test_blocking_victims_selects_only_foreign_pairs_and_never_drops_in_vain():
    inventory = Inventory(graph(), 2)
    assert inventory.blocking_victims((1, 2)) == []
    own = inventory.generate((1, 2), 0)[0]
    assert inventory.blocking_victims((1, 2)) is None            # blocked by its own elementary pair
    inventory.remove(own.identifier, 0, "test")
    foreign = inventory._insert((0, 1), 0, None, {0: 1, 1: 2})   # center qubit in the slot toward 2
    assert inventory.blocking_victims((1, 2)) == [foreign.identifier]
    assert inventory.blocking_victims((1, 2), lambda item: False) is None
    # Both ends blocked: a cached end-to-end pair holds node 2's only slot.
    cached = Inventory(graph(), {0: 2, 1: 2, 2: 1})
    trap = cached._insert((0, 1), 0, None, {0: 1, 1: 2})
    held = cached._insert((0, 2), 1, None, {0: 1, 2: 1})
    assert cached.blocking_victims((1, 2)) == [trap.identifier, held.identifier]
    # If only one end has an eligible candidate, nothing is dropped.
    assert cached.blocking_victims((1, 2), lambda item: item is trap) is None


def test_shared_pool_victim_is_the_longest_stored_pair_at_the_full_node():
    inventory = Inventory(graph(), 2, admission_policy="tail_drop")
    first = inventory.generate((0, 1), 1)[0]
    inventory.generate((0, 1), 2)
    assert inventory.admission_reason((1, 2)) == "hard_slots"
    assert inventory.blocking_victims((1, 2)) == [first.identifier]


def test_service_continuity_measures_interruptions_per_pair_and_clips_to_the_window():
    link = nx.path_graph(2)
    nx.set_edge_attributes(link, 1.0, "generation_capacity")
    trace = [event(1, "request", [0, 1]), event(2, "request", [0, 1]), event(4, "generate", [0, 1]),
             event(7, "generate", [0, 1]), event(8, "request", [0, 1])]
    kwargs = dict(horizon=10, ticks_per_time_unit=100, trace=trace, memory_slots=2, outage_threshold=3)
    whole = run_simulation(link, {(0, 1): 0.5}, **kwargs)["service_continuity"]
    pair = whole["by_pair"][0]
    assert (pair["interruptions"], pair["interrupted_time"], pair["longest_interruption"]) == (3, 8, 3)
    assert (pair["outages"], pair["outage_time"], pair["trailing_interruption"]) == (2, 6, 2)
    assert pair["right_censored"] and not pair["starved"] and pair["waiting_at_horizon"] == 1
    assert pair["satisfaction"] == pytest.approx(2 / (10 * 0.5))
    assert whole["all_pairs"] == {key: pair[key] for key in whole["all_pairs"]}
    clipped = run_simulation(link, {(0, 1): 0.5}, measure_from=5, **kwargs)["service_continuity"]["by_pair"][0]
    assert (clipped["interruptions"], clipped["interrupted_time"], clipped["outages"]) == (2, 4, 0)
    assert (clipped["offered_requests"], clipped["completed_requests"]) == (1, 1)


def test_a_pair_that_waits_through_the_window_without_service_is_starved():
    result = simulate([event(1, "request", [0, 2]), event(2, "generate", [0, 1])],
                      memory_slots=2, measure_from=5, outage_threshold=10)
    continuity = result["service_continuity"]
    assert continuity["starved_pairs"] == 1 and continuity["minimum_satisfaction"] == 0
    assert continuity["by_pair"][0]["longest_interruption"] == 15
    assert continuity["by_pair"][0]["outage_fraction"] == 1


def test_per_pair_service_removes_head_of_line_blocking_and_fifo_keeps_it():
    trace = [event(1, "request", [0, 2]), event(2, "request", [0, 1]), event(3, "generate", [0, 1])]
    demand = {(0, 2): 1.0, (0, 1): 1.0}
    fifo = simulate(trace, demand=demand, memory_slots=4, swap_policy="none")
    separate = simulate(trace, demand=demand, memory_slots=4, swap_policy="none", service_order="per_pair")
    assert fifo["completed_requests"] == 0 and fifo["request_regime"] == "offered-unbounded-global-fifo"
    assert separate["completed_requests"] == 1 and separate["unserved_requests"] == 1
    assert [row["endpoints"] for row in separate["unserved_queue"]] == [[0, 2]]
    assert separate["service_continuity"]["by_pair"][1]["completed_requests"] == 1


@pytest.mark.parametrize("kwargs", [{"recovery_policy": "flush"}, {"service_order": "random"},
                                    {"stuck_patience": -1}, {"measure_from": 20}, {"outage_threshold": 0}])
def test_invalid_recovery_and_measurement_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        simulate([], memory_slots=2, **kwargs)


def test_configuration_accepts_the_new_simulation_keys():
    data = {"nodes": [0, 1, 2],
            "edges": [{"nodes": [0, 1], "generation_capacity": 1}, {"nodes": [1, 2], "generation_capacity": 1}],
            "demand_rate": [{"pair": [0, 2], "rate": 0.2}], "mean_residence_time": 1, "memory_slots": 2,
            "time_unit": "abstract", "residence_time_source": "test", "demand_normalization": "test",
            "simulation": {"recovery_policy": "drop_when_stuck", "stuck_patience": 5,
                           "service_order": "per_pair", "measure_from": 10, "outage_threshold": 50}}
    assert parse_config(data).simulation["stuck_patience"] == 5
    data["simulation"]["recovery_policy"] = "flush"
    with pytest.raises(ValueError):
        parse_config(data)


def verdict(topology, memory, policy="pressure_relaxed", **options):
    edges, demand = TOPOLOGIES[topology]
    return analyse(Arm(edges, demand, memory, policy, **options))[0]


def test_zero_patience_drop_removes_every_small_lockup_that_swap_conditions_leave():
    for topology, memory in (("chain", 2), ("chain4", 3), ("diamond", 2), ("cycle5", 2), ("cycle5", 3)):
        assert verdict(topology, memory)["verdict"] != "no lockup"
        assert verdict(topology, memory, drop_stuck=True)["verdict"] == "no lockup"
    assert verdict("cycle5", 2, "pressure_oriented", no_shortcut=True, drop_stuck=True)["verdict"] == "no lockup"
    assert verdict("cycle6", 2, geodesic=True, drop_stuck=True)["verdict"] == "no lockup"


def test_shared_pool_admission_locks_at_budgets_where_reservations_do_not():
    for memory in (3, 4):
        assert verdict("chain", memory)["verdict"] == "no lockup"
        shared = verdict("chain", memory, admission="tail_drop")
        assert shared["verdict"] == "dead classes only"
        assert "01 " * (memory - 1) + "01" in shared["frozen_inventories"]
        assert verdict("chain", memory, "pressure_oriented", admission="tail_drop")["verdict"] != "no lockup"
        assert verdict("chain", memory, admission="tail_drop", drop_stuck=True)["verdict"] == "no lockup"


def test_search_with_drop_and_shared_pool_matches_the_public_simulator():
    assert check_against_simulator("chain", 2, "pressure_relaxed", samples=20, length=30, drop_stuck=True) == 20
    assert check_against_simulator("diamond", 3, "pressure_oriented", samples=10, length=50,
                                   drop_stuck=True, admission="tail_drop") == 10
    assert check_against_simulator("cycle5-two", 3, "pressure_relaxed", samples=10, length=60,
                                   admission="tail_drop") == 10


def test_runner_demand_is_seeded_sparse_and_normalised():
    network = recovery_baseline.network("cycle8")
    demand, hops = recovery_baseline.demand_set(network, 11301, 0.12, 0.1)
    assert demand == recovery_baseline.demand_set(network, 11301, 0.12, 0.1)[0]
    assert len(demand) == 3 and min(hops.values()) >= 2
    assert sum(rate * hops[pair] for pair, rate in demand.items()) == pytest.approx(0.1 * 8)
    assert demand != recovery_baseline.demand_set(network, 11302, 0.12, 0.1)[0]


def test_runner_arms_and_one_small_paired_comparison():
    assert recovery_baseline.parse_arm("none") == {}
    assert recovery_baseline.parse_arm("drop2.5") == {"recovery_policy": "drop_when_stuck", "stuck_patience": 2.5}
    assert recovery_baseline.parse_arm("cutoff30") == {"cutoff_time": 30.0}
    with pytest.raises(ValueError):
        recovery_baseline.parse_arm("flush")
    options = {"share": 0.12, "load": 0.1, "horizon": 300, "warmup": 100, "outage": 50}
    rows = [recovery_baseline.run(("cycle8", 2, "pressure_relaxed", "reserved", arm, 11301, options))
            for arm in ("none", "drop0")]
    assert rows[0]["demand_rate"] == rows[1]["demand_rate"]
    assert rows[0]["drops_per_completion"] in (0, None) and rows[1]["drops_per_completion"] > 0
    assert rows[1]["satisfaction"] > rows[0]["satisfaction"]
    assert rows[1]["starved_fraction"] == 0 < rows[0]["starved_fraction"]
    summary = recovery_baseline.summarise(rows)
    assert [group["arm"] for group in summary] == ["none", "drop0"]
    assert summary[0]["satisfaction"][1:] == [None, None]

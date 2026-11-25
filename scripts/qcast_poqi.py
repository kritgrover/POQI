"""Opportunity-clock POQI arms for the explicitly labelled Q-CAST pilot.

This is a phase wrapper, not the root continuous-time simulator. Attempts are
reserved at a slot's start, then outcomes are revealed and successful links
installed as a batch at its end. The root's settling implementation, pressure
predicate, physical inventory and input ordering are reused without edits.
Demand consumption belongs to the common external workload observer.
"""

from collections import Counter

from poqi.simulation.inventory import Inventory
from poqi.simulation.sequence_adapter import _SequenceSimulation


class _Clock:
    def __init__(self):
        self.tick = 0

    def now(self):
        return self.tick


class PoqiOpportunityArm:
    """D=1, q=1, finite-memory arm with unit-duration physical opportunities.

    ``ordered_channels`` contains ``(u,v,channel_id)`` triples, with stable IDs
    for parallel channels. Ordering is exogenous and supplied by the caller.
    Failed attempts occupy their reserved endpoint qubits for the whole slot.
    Existing pairs occupy endpoint slots but do not monopolize optical channels.
    """

    _settle = _SequenceSimulation._settle
    _under_pressure = _SequenceSimulation._under_pressure
    _oriented_inputs = _SequenceSimulation._oriented_inputs
    _swap = _SequenceSimulation._swap
    _pair_record = staticmethod(_SequenceSimulation._pair_record)

    def __init__(self, graph, memory, policy, persistence, cutoff=None, admission="reserved"):
        if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0:
            raise ValueError("memory must be a finite nonnegative integer")
        if policy not in {"balancing", "pressure_relaxed", "pressure_oriented"}:
            raise ValueError("pilot policy must be balancing, pressure_relaxed, or pressure_oriented")
        if type(persistence) is not bool:
            raise ValueError("persistence must be boolean")
        if cutoff is not None and (isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff < 1):
            raise ValueError("cutoff must be a positive integer number of slots")
        if tuple(graph.nodes) != tuple(range(len(graph))):
            raise ValueError("pilot graph nodes must be ordered 0..n-1")
        self.inventory = Inventory(graph, memory, admission_policy=admission, distillation_pairs=1)
        self.swap_policy, self.admission_policy = policy, admission
        self.persistence, self.cutoff = persistence, cutoff
        self.timeline = _Clock()
        self.counters = Counter()
        self._phase = "idle"
        self._end = 0
        self._selected = {}
        self._events = []
        self._slot_consumed = 0

    def _schedule_expiry(self, item):
        # All lifetimes and decisions are integer-slot boundaries in this arm.
        # Inventory.swap already preserves the minimum physical input deadline.
        pass

    def _drain(self):
        # The common workload layer applies the chosen FIFO/concurrent contract.
        pass

    def _log(self, kind, **details):
        self._events.append({"kind": kind, "tick": self.timeline.now(), **details})

    @staticmethod
    def _integer_time(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("time must be a nonnegative integer slot boundary")

    def snapshot(self):
        return [self._pair_record(item) for item in self.inventory.pairs.values()]

    def ebit_counts(self):
        return {pair: len(ids) for pair, ids in self.inventory.buffers.items() if ids}

    def _expire(self, tick):
        expired = [item.identifier for item in self.inventory.pairs.values()
                   if item.deadline is not None and item.deadline <= tick]
        for identifier in expired:
            self.inventory.remove(identifier, tick, "expiry")
        self.counters["expired_pairs"] += len(expired)
        return expired

    def _check(self):
        self.inventory.validate()
        expected = (self.counters["generated_pairs"] - self.counters["swaps"]
                    - self.counters["consumed_pairs"] - self.counters["expired_pairs"]
                    - self.counters["discarded_pairs"])
        if len(self.inventory.pairs) != expected:
            raise AssertionError("opportunity arm pair conservation failed")

    def begin_slot(self, start, ordered_channels):
        self._integer_time(start)
        if self._phase != "idle" or start != self._end:
            raise ValueError("slots must be contiguous and the preceding slot finished")
        # Validate every input before mutating state or exposing any allocation.
        channels = []
        seen = set()
        for u, v, identifier in ordered_channels:
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 0 or identifier in seen:
                raise ValueError("channel IDs must be unique nonnegative integers")
            edge = self.inventory.pair(u, v)
            if edge not in self.inventory.physical_edges:
                raise ValueError("channel must be a physical edge")
            channels.append((edge, identifier))
            seen.add(identifier)
        self.timeline.tick = start
        self.inventory.advance(start)
        self._events = []
        self._slot_consumed = 0
        self._expired_at_start = self._expire(start)
        self._check()
        self._pre_count = len(self.inventory.pairs)
        occupied = self.inventory.occupancy.copy()
        origins = self.inventory.origin_occupancy.copy()
        self._selected = {}
        blocked = []
        for edge, identifier in channels:
            reason = None
            for node, neighbor in (edge, edge[::-1]):
                if occupied[node] >= self.inventory.limits[node]:
                    reason = "hard_slots"
                    break
                if (self.admission_policy == "reserved"
                        and origins[node, neighbor] >= self.inventory.quotas[node][neighbor]):
                    reason = "neighbor_reservation"
                    break
            if reason:
                blocked.append({"channel": identifier, "reason": reason})
            else:
                self._selected[identifier] = edge
                for node, neighbor in (edge, edge[::-1]):
                    occupied[node] += 1
                    origins[node, neighbor] += 1
        self._start = start
        self._phase = "planned"
        self._swaps_before = self.counters["swaps"]
        self._relaxed_before = self.counters["pressure_relaxed_swaps"]
        self.counters["attempts"] += len(self._selected)
        self.counters["blocked_opportunities"] += len(blocked)
        storage = 2 * self._pre_count
        attempt = 2 * len(self._selected)
        if any(occupied[n] > self.inventory.limits[n] for n in self.inventory.nodes):
            raise AssertionError("in-flight memory reservation exceeds capacity")
        return {
            "selected": list(self._selected), "blocked": blocked,
            "pre_live_pairs": self._pre_count,
            "pre_occupancy": [self.inventory.occupancy[n] for n in self.inventory.nodes],
            "reserved_occupancy": [occupied[n] for n in self.inventory.nodes],
            "qubit_time": storage + attempt, "storage_qubit_time": storage,
            "attempt_qubit_time": attempt, "expired_at_start": len(self._expired_at_start),
        }

    def end_slot(self, end, successful_ids):
        self._integer_time(end)
        if self._phase != "planned" or end != self._start + 1:
            raise ValueError("end_slot requires a planned unit-duration slot")
        successful_ids = list(successful_ids)
        if len(successful_ids) != len(set(successful_ids)) or not set(successful_ids) <= set(self._selected):
            raise ValueError("successful IDs must be distinct selected channel IDs")
        self.timeline.tick = end
        self.inventory.advance(end)
        expired = self._expire(end)
        successful = set(successful_ids)
        generated = []
        deadline = None if self.cutoff is None else end + self.cutoff
        # Iterate in original reservation order, never outcome-dependent order.
        for identifier, edge in self._selected.items():
            if identifier not in successful:
                continue
            item, reason = self.inventory.generate(edge, end, deadline)
            if reason or item is None:
                raise AssertionError("pre-reserved successful generation was rejected")
            generated.append({"channel": identifier, "pair": self._pair_record(item)})
            self.counters["generated_pairs"] += 1
        self.counters["failed_attempts"] += len(self._selected) - len(successful)
        self._settle()
        self._check()
        self._end = end
        self._phase = "settled"
        return {
            "generated_pairs": len(generated), "generated": generated,
            "expired_pairs": len(expired) + len(self._expired_at_start),
            "expired_ids": self._expired_at_start + expired,
            "swaps": self.counters["swaps"] - self._swaps_before,
            "pressure_relaxed_swaps": self.counters["pressure_relaxed_swaps"] - self._relaxed_before,
            "live_pairs": self.snapshot(), "swap_log": list(self._events),
        }

    def consume(self, pair, end):
        self._integer_time(end)
        allowed_phase = self._phase == "settled" or (self._phase == "idle" and self.persistence)
        if not allowed_phase or end != self._end:
            raise ValueError("consumption is only allowed at the current boundary outside an attempt")
        endpoints = self.inventory.pair(*pair)
        ids = self.inventory.oldest(endpoints, 1)
        if not ids:
            return None
        item = self.inventory.remove(ids[0], end, "consumption")
        self.counters["consumed_pairs"] += 1
        self._slot_consumed += 1
        self._check()
        return self._pair_record(item)

    def finish_slot(self, end):
        self._integer_time(end)
        if self._phase != "settled" or end != self._end:
            raise ValueError("finish_slot requires the current settled boundary")
        discarded = list(self.inventory.pairs) if not self.persistence else []
        for identifier in discarded:
            self.inventory.remove(identifier, end, "slot_reset")
        self.counters["discarded_pairs"] += len(discarded)
        self._check()
        self._phase = "idle"
        return {"discarded_pairs": len(discarded), "discarded_ids": discarded,
                "remaining_pairs": len(self.inventory.pairs), "live_pairs": self.snapshot(),
                "consumed_pairs": self._slot_consumed}

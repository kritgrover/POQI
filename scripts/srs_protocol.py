"""Matched slotted Bell-pair protocols for a queued-request experiment.

SRS follows Iñesta & Wehner, PRA 108, 052615, Algorithm 1, and
https://github.com/AlvaroGI/optimizing-cd-protocols/blob/3a68a05663a61dacefa59809646c55bcfaf2a493/main_cd.py#L364-L425 .
Each pivot selects physical qubits from the same pre-swap snapshot. A serial
execution of those fixed measurements implements simultaneous adjacent swaps.
Failure propagates to their final output before classical results are known.
The native probabilistic consumption of existing links is replaced by per-pair
FIFO service of a common external request stream. Both arms serve after length
filtering, taking earliest physical deadline, oldest buffer episode, then ID.
The caller supplies an ordered map of potential heralds for the common link
opportunities. Its iteration order breaks contention between eviction attempts.
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import random

import networkx as nx

from poqi.simulation.inventory import Inventory
from poqi.simulation.sequence_adapter import _SequenceSimulation


@dataclass(frozen=True)
class _Link:
    ends: tuple
    born: int
    admitted: int
    segments: int
    good: bool
    serial: int

    def other(self, address):
        return self.ends[1] if address == self.ends[0] else self.ends[0]


class _RandomSwap:
    """Physical register addresses survive changes of entangled partner."""

    def __init__(self, graph, slots, rng, counters):
        inventory = Inventory(graph, slots)
        self.edges = inventory.physical_edges
        self.nodes = inventory.nodes
        self.rng = rng
        self.counters = counters
        self.registers = {
            (u, v): tuple((u, v, i) for i in range(size))
            for u, quotas in inventory.quotas.items() for v, size in quotas.items()
        }
        self.addresses = {
            u: tuple(addr for v in sorted(graph.neighbors(u)) for addr in self.registers[u, v])
            for u in self.nodes
        }
        self.at = {}
        self.links = {}
        self.serial = 0

    def add(self, left, right, born, now, segments=1, good=True):
        link = _Link((left, right), born, now, segments, good, self.serial)
        self.serial += 1
        self.at[left] = self.at[right] = link
        self.links[link.serial] = link

    def remove(self, link):
        for address in link.ends:
            del self.at[address]
        del self.links[link.serial]

    def expire(self, now, cutoff):
        if cutoff is None:
            return
        for link in list(self.links.values()):
            if now - link.born >= cutoff:
                self.remove(link)
                self.counters["expired"] += 1

    def generate(self, pair, success, now):
        left = next((a for a in self.registers[pair] if a not in self.at), None)
        right = next((a for a in self.registers[pair[::-1]] if a not in self.at), None)
        if left is None or right is None:
            return
        self.counters["attempts"] += 1
        if success:
            self.add(left, right, now, now)
            self.counters["admitted"] += 1

    def swap_round(self, now, attempt, success, max_length):
        if attempt == 0:
            return
        nodes = list(self.nodes)
        self.rng.shuffle(nodes)
        choices = []
        for node in nodes:
            occupied = [a for a in self.addresses[node] if a in self.at]
            if len(occupied) < 2:
                continue
            self.rng.shuffle(occupied)
            first = occupied[0]
            j = self.at[first].other(first)[0]
            for second in occupied[1:]:
                k = self.at[second].other(second)[0]
                if k != j and (min(j, k), max(j, k)) not in self.edges:
                    choices.append((first, second))
                    break
        for left_addr, right_addr in choices:
            if self.rng.random() >= attempt:
                continue
            left, right = self.at[left_addr], self.at[right_addr]
            operation_succeeded = self.rng.random() < success
            self.counters["swaps"] += 1
            self.counters["swap_successes"] += int(operation_succeeded)
            left_out, right_out = left.other(left_addr), right.other(right_addr)
            self.remove(left)
            if left.serial == right.serial:
                # All qubits in a closed cycle of simultaneous swaps were measured.
                continue
            self.remove(right)
            self.add(left_out, right_out, min(left.born, right.born), now,
                     left.segments + right.segments, left.good and right.good and operation_succeeded)
        for link in list(self.links.values()):
            if not link.good:
                self.remove(link)
            elif max_length is not None and link.segments > max_length:
                self.remove(link)
                self.counters["over_length"] += 1

    def available(self, pair):
        links = (self.at[a] for a in self.addresses[pair[0]]
                 if a in self.at and self.at[a].other(a)[0] == pair[1])
        return sorted(links, key=lambda item: (item.born if self.cutoff_active else 0,
                                               item.admitted, item.serial))

    def consume(self, item, now):
        self.remove(item)


class _Pressure:
    """The production oriented pressure selector and serial settling loop."""

    _under_pressure = _SequenceSimulation._under_pressure
    _oriented_inputs = _SequenceSimulation._oriented_inputs
    swap_policy = "pressure_oriented"
    admission_policy = "reserved"

    def __init__(self, graph, slots, rng, counters, policy, cutoff, success):
        self.inventory = Inventory(graph, slots)
        self.rng = rng
        self.counters = counters
        self.policy = policy
        self.cutoff = cutoff
        self.success = success
        self.segments = {}

    def remove(self, identifier, now, reason):
        self.inventory.remove(identifier, now, reason)
        del self.segments[identifier]

    def expire(self, now, cutoff):
        if cutoff is not None:
            for item in list(self.inventory.pairs.values()):
                if item.deadline <= now:
                    self.remove(item.identifier, now, "expiry")
                    self.counters["expired"] += 1

    def generate(self, pair, success, now):
        victims = []
        if self.inventory.admission_reason(pair):
            if self.policy == "pressure_oriented":
                return
            victims = self.inventory.blocking_victims(pair)
            if not victims:
                return
        self.counters["attempts"] += 1
        if self.policy == "pressure_pre_drop" or success:
            for identifier in victims:
                self.remove(identifier, now, "eviction")
                self.counters["dropped"] += 1
        if success:
            deadline = None if self.cutoff is None else now + self.cutoff
            item, reason = self.inventory.generate(pair, now, deadline)
            if reason:
                raise AssertionError("eligible herald could not occupy its slot")
            self.segments[item.identifier] = 1
            self.counters["admitted"] += 1

    def _swap(self, pivot, pair, *, pressure_relaxed=False, input_ids=None):
        self.counters["swaps"] += 1
        if self.rng.random() >= self.success:
            for identifier in input_ids:
                self.remove(identifier, self.now, "failed_swap")
            return
        output, inputs = self.inventory.swap(pivot, pair, self.now, input_ids=input_ids)
        self.segments[output.identifier] = sum(self.segments.pop(i) for i in inputs)
        self.counters["swap_successes"] += 1

    def _drain(self):
        # All arms release over-length outputs before running the same demand service.
        pass

    def swap_round(self, now, attempt, success, max_length):
        self.now = now
        _SequenceSimulation._settle(self)
        if max_length is not None:
            for identifier, segments in list(self.segments.items()):
                if segments > max_length:
                    self.remove(identifier, now, "length")
                    self.counters["over_length"] += 1

    def available(self, pair):
        return self.inventory.oldest(pair)

    def consume(self, item, now):
        self.remove(item, now, "consumption")


class SlottedProtocol:
    """One slotted protocol with matched FIFO demand. Nodes are integer labels."""

    def __init__(self, edges, slots, *, policy, seed, cutoff, max_length,
                 swap_success=1.0, swap_attempt=1.0):
        if policy not in {"srs", "pressure_oriented", "pressure_pre_drop", "pressure_post_drop"}:
            raise ValueError("unknown slotted protocol")
        if not 0 <= swap_success <= 1 or not 0 <= swap_attempt <= 1:
            raise ValueError("swap probabilities must be in [0, 1]")
        if policy != "srs" and swap_attempt != 1:
            raise ValueError("swap_attempt tunes the single random swap protocol only")
        for cap in (cutoff, max_length):
            if cap is not None and (type(cap) is not int or cap < 1):
                raise ValueError("cutoff and max_length must be positive integers or None")
        edges = tuple(edges)
        graph = nx.Graph()
        graph.add_nodes_from(sorted({node for edge in edges for node in edge}))
        graph.add_edges_from(sorted(edges))
        self.edges = {tuple(sorted(edge)) for edge in graph.edges}
        self.nodes = set(graph)
        self.cutoff, self.max_length = cutoff, max_length
        self.swap_success, self.swap_attempt = swap_success, swap_attempt
        self.counters = Counter()
        self.queues = defaultdict(deque)
        self.tick = None
        rng = random.Random(seed)
        if policy == "srs":
            self.backend = _RandomSwap(graph, slots, rng, self.counters)
            self.backend.cutoff_active = cutoff is not None
        else:
            self.backend = _Pressure(graph, slots, rng, self.counters, policy, cutoff, swap_success)

    @property
    def pending(self):
        return sum(map(len, self.queues.values()))

    def step(self, tick, link_successes, arrivals=()):
        """Run one slot. Return (endpoint pair, original arrival tick) for each completion.

        Supply every undirected physical edge once as an ascending node pair.
        'attempts' counts viable or evictable opportunities actually tried, while
        'herald_successes' counts all supplied potential successes, including blocked ones.
        The post-drop counterfactual charges an attempt on an evictable link, but releases
        its contested memory only once it knows generation will succeed.
        """
        if self.tick is not None and tick != self.tick + 1:
            raise ValueError("ticks must be consecutive")
        if link_successes.keys() != self.edges:
            raise ValueError("each physical edge must have one potential generation outcome")
        self.tick = tick
        self.backend.expire(tick, self.cutoff)
        for pair, success in link_successes.items():
            self.counters["offered_generation"] += 1
            self.counters["herald_successes"] += int(success)
            self.backend.generate(pair, success, tick)
        self.backend.swap_round(tick, self.swap_attempt, self.swap_success, self.max_length)
        for pair in arrivals:
            u, v = pair
            if u == v or u not in self.nodes or v not in self.nodes:
                raise ValueError("request endpoints must be distinct known nodes")
            self.queues[(min(u, v), max(u, v))].append(tick)
        completed = []
        for pair, queue in self.queues.items():
            if queue:
                for item in self.backend.available(pair)[:len(queue)]:
                    self.backend.consume(item, tick)
                    completed.append((pair, queue.popleft()))
        return completed

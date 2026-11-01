"""Finite Bell-pair inventory; event timing belongs to SeQUeNCe.

Each pair is one buffer episode. A swap ends its input episodes and starts an
output episode, while the output retains the earliest physical deadline.
"""

from dataclasses import dataclass
import math
from collections import Counter, defaultdict


@dataclass(frozen=True)
class Pair:
    identifier: int
    endpoints: tuple
    admitted: int
    deadline: int | None
    origins: dict
    parents: tuple = ()


class Inventory:
    """Atomic admission and swap accounting with optional neighbor reservations.

    Reserved admission divides each node's slots between physical neighbors;
    the first neighbors in graph order receive the remainder. Reservations track
    a local qubit's generation edge even after its entangled partner changes.
    This avoids one input taking every pivot slot when every neighbor has a
    positive quota. It can intentionally leave slots unused.
    """

    def __init__(self, graph, memory_slots=None, *, admission_policy="reserved",
                 distillation_pairs=1):
        if graph.is_directed() or graph.is_multigraph():
            raise ValueError("graph must be a simple undirected graph")
        if any(u == v for u, v in graph.edges):
            raise ValueError("self links are not supported")
        self.nodes = tuple(graph.nodes)
        self.order = {node: i for i, node in enumerate(self.nodes)}
        if not self.nodes:
            raise ValueError("graph must contain nodes")
        if isinstance(distillation_pairs, bool) or not isinstance(distillation_pairs, int) or distillation_pairs < 1:
            raise ValueError("distillation_pairs must be a positive integer")
        self.D = distillation_pairs
        if admission_policy not in {"reserved", "tail_drop"}:
            raise ValueError("admission_policy must be reserved or tail_drop")
        self.admission_policy = admission_policy
        if memory_slots is None:
            self.limits = {node: None for node in self.nodes}
        else:
            if isinstance(memory_slots, dict):
                if set(memory_slots) != set(self.nodes):
                    raise ValueError("memory_slots must cover exactly the graph nodes")
                limits = memory_slots
            else:
                limits = {node: memory_slots for node in self.nodes}
            for value in limits.values():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value != int(value):
                    raise ValueError("hard memory_slots must be nonnegative integers")
            self.limits = {node: int(value) for node, value in limits.items()}
        self.quotas = {}
        for node in self.nodes:
            neighbors = sorted(graph.neighbors(node), key=self.order.__getitem__)
            if self.limits[node] is not None and neighbors:
                base, remainder = divmod(self.limits[node], len(neighbors))
                self.quotas[node] = {neighbor: base + (i < remainder) for i, neighbor in enumerate(neighbors)}
        self.physical_edges = {self.pair(u, v) for u, v in graph.edges}
        self.pairs = {}
        self.buffers = defaultdict(list)
        self.occupancy = Counter({node: 0 for node in self.nodes})
        self.peak_occupancy = self.occupancy.copy()
        self.origin_occupancy = Counter()
        self.area = Counter({node: 0.0 for node in self.nodes})
        self.pair_area = Counter()
        self.last_tick = 0
        self.next_id = 0
        self.episode_arrivals = Counter()
        self.episode_departures = Counter()
        self.departed_residence = Counter()
        self.departures_by_reason = Counter()

    def pair(self, u, v):
        if u not in self.order or v not in self.order or u == v:
            raise ValueError("pair endpoints must be distinct known graph nodes")
        return (u, v) if self.order[u] < self.order[v] else (v, u)

    def advance(self, tick):
        if tick < self.last_tick:
            raise ValueError("inventory cannot move backwards in time")
        elapsed = tick - self.last_tick
        for node, count in self.occupancy.items():
            self.area[node] += count * elapsed
        for endpoints, ids in self.buffers.items():
            self.pair_area[endpoints] += len(ids) * elapsed
        self.last_tick = tick

    def admission_reason(self, endpoints):
        if endpoints not in self.physical_edges:
            raise ValueError("physical generation requires a physical edge")
        for node, neighbor in (endpoints, endpoints[::-1]):
            limit = self.limits[node]
            if limit is not None and self.occupancy[node] >= limit:
                return "hard_slots"
            if (self.admission_policy == "reserved" and node in self.quotas
                    and self.origin_occupancy[node, neighbor] >= self.quotas[node][neighbor]):
                return "neighbor_reservation"
        return None

    def _insert(self, endpoints, tick, deadline, origins, parents=()):
        item = Pair(self.next_id, endpoints, tick, deadline, origins, parents)
        self.next_id += 1
        self.pairs[item.identifier] = item
        self.buffers[endpoints].append(item.identifier)
        self.episode_arrivals[endpoints] += 1
        for node in endpoints:
            self.occupancy[node] += 1
            self.origin_occupancy[node, origins[node]] += 1
            self.peak_occupancy[node] = max(self.peak_occupancy[node], self.occupancy[node])
        self.validate()
        return item

    def generate(self, endpoints, tick, deadline=None):
        self.advance(tick)
        reason = self.admission_reason(endpoints)
        if reason:
            return None, reason
        u, v = endpoints
        return self._insert(endpoints, tick, deadline, {u: v, v: u}), None

    def remove(self, identifier, tick, reason):
        self.advance(tick)
        item = self.pairs.pop(identifier)
        self.buffers[item.endpoints].remove(identifier)
        for node in item.endpoints:
            self.occupancy[node] -= 1
            self.origin_occupancy[node, item.origins[node]] -= 1
        self.episode_departures[item.endpoints] += 1
        self.departed_residence[item.endpoints] += tick - item.admitted
        self.departures_by_reason[reason] += 1
        return item

    def oldest(self, endpoints, count):
        # Earliest deadline first, then oldest buffer episode, then identifier.
        return sorted(self.buffers[endpoints], key=lambda identifier: (
            self.pairs[identifier].deadline if self.pairs[identifier].deadline is not None else math.inf,
            self.pairs[identifier].admitted, identifier))[:count]

    def swap(self, pivot, endpoints, tick):
        x, y = endpoints
        if pivot in endpoints or pivot not in self.order:
            raise ValueError("swap pivot must be a third known node")
        left, right = self.pair(pivot, x), self.pair(pivot, y)
        if len(self.buffers[left]) < self.D or len(self.buffers[right]) < self.D:
            return None, []
        self.advance(tick)
        left_ids, right_ids = self.oldest(left, self.D), self.oldest(right, self.D)
        origins = {x: self.pairs[left_ids[0]].origins[x], y: self.pairs[right_ids[0]].origins[y]}
        parents = tuple(left_ids + right_ids)
        deadlines = [self.pairs[i].deadline for i in parents if self.pairs[i].deadline is not None]
        deadline = min(deadlines) if deadlines else None
        for identifier in parents:
            self.remove(identifier, tick, "swap_input")
        # Input removal releases endpoint slots first; no fictitious extra slot.
        output = self._insert(endpoints, tick, deadline, origins, parents)
        return output, list(parents)

    def validate(self):
        expected = Counter({node: 0 for node in self.nodes})
        for item in self.pairs.values():
            expected.update(item.endpoints)
        if expected != self.occupancy:
            raise AssertionError("occupancy does not match live pair endpoints")
        for node, count in self.occupancy.items():
            limit = self.limits[node]
            if count < 0 or (limit is not None and count > limit):
                raise AssertionError("hard memory capacity violated")


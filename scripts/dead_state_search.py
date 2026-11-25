"""Exhaustive search for inventories that can never serve again without expiry.

Every inventory reachable from empty is enumerated by applying each possible
next event (one generation on a physical edge, or one request) and letting the
actual swap policy settle. The repository's settling, pressure, orientation and
inventory code are reused unchanged. Only event timing is abstracted away, which
is harmless without expiry because the policy never reads the clock.

A closed set of states with no completion of some demand class is a structural
lockup for that class. A closed set with no completion at all is a dead class.
A single inventory that no event changes is a frozen inventory.

Service is concurrent per demand pair. With one demand class this is the root
simulator's FIFO. Pending counts are capped at ``CAP``, read as "at least CAP",
with every consistent successor explored, so reachability is exact.

Two experimental filters are available. Neither is a production policy.
``--no-shortcut``: a swap may not create a pair between two physical neighbors.
This is the swap condition of Iñesta and Wehner, Phys. Rev. A 108, 052615 (2023).
``--geodesic``: the pivot must lie on a shortest physical path between the two
new endpoints. It implies the no-shortcut condition.
``Arm(..., asap=True)`` drops the count thresholds, so every physically possible
swap that the selected policy's input rule allows is taken at once.
"""

import argparse
from collections import Counter, deque
from itertools import combinations, product
import json
import random

import networkx as nx

from poqi.simulation import run_simulation
from poqi.simulation.inventory import Inventory
from poqi.simulation.sequence_adapter import _SequenceSimulation

CAP = 3
RULES = {  # name -> (policy, no_shortcut, geodesic)
    "none": ("pressure_relaxed", False, False),
    "orientation": ("pressure_oriented", False, False),
    "no-shortcut": ("pressure_relaxed", True, False),
    "both": ("pressure_oriented", True, False),
    "geodesic": ("pressure_relaxed", False, True),
}
TOPOLOGIES = {
    "chain": (((0, 1), (1, 2)), ((0, 2),)),
    "chain4": (((0, 1), (1, 2), (2, 3)), ((0, 3),)),
    "chain5": (((0, 1), (1, 2), (2, 3), (3, 4)), ((0, 4),)),
    "chain5-mixed": (((0, 1), (1, 2), (2, 3), (3, 4)), ((0, 4), (1, 3))),
    "chain6": (((0, 1), (1, 2), (2, 3), (3, 4), (4, 5)), ((0, 5),)),
    "diamond": (((0, 1), (0, 2), (1, 3), (2, 3)), ((0, 3), (0, 1), (1, 2))),
    "diamond-diagonals": (((0, 1), (0, 2), (1, 3), (2, 3)), ((0, 3), (1, 2))),
    "star": (((0, 1), (0, 2), (0, 3)), ((1, 2), (1, 3), (2, 3))),
    "cycle5": (((0, 1), (1, 2), (2, 3), (3, 4), (0, 4)), ((0, 2),)),
    "cycle5-two": (((0, 1), (1, 2), (2, 3), (3, 4), (0, 4)), ((0, 2), (1, 3))),
    "cycle6": (((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 5)), ((0, 3),)),
    "cycle6-two": (((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 5)), ((0, 3), (1, 4))),
    "grid2x3": (((0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)), ((0, 5),)),
}


class _Clock:
    @staticmethod
    def now():
        return 0


class Arm:
    """Untimed driver around the repository's policy code."""

    _reference_settle = _SequenceSimulation._settle
    _under_pressure = _SequenceSimulation._under_pressure
    _oriented_inputs = _SequenceSimulation._oriented_inputs
    _swap = _SequenceSimulation._swap
    _pair_record = staticmethod(_SequenceSimulation._pair_record)

    def __init__(self, edges, demand, memory, policy, *, no_shortcut=False, geodesic=False, asap=False):
        self.graph = nx.Graph()
        self.graph.add_nodes_from(range(1 + max(max(edge) for edge in edges)))
        self.graph.add_edges_from(edges)
        self.edges = tuple(edges)
        self.demand = tuple(demand)
        # One budget for every node, or one budget per node in node order.
        self.memory = dict(enumerate(memory)) if isinstance(memory, (tuple, list)) else memory
        self.swap_policy, self.no_shortcut, self.geodesic, self.asap = policy, no_shortcut, geodesic, asap
        self.distance = dict(nx.all_pairs_shortest_path_length(self.graph))
        self.admission_policy = "reserved"
        self.timeline = _Clock()
        self.counters = Counter()
        self.swap_log = []
        self.restore(())

    # Hooks the borrowed methods call.
    def _schedule_expiry(self, item):
        pass

    def _log(self, kind, **details):
        if kind == "swap":
            self.swap_log.append((details["pivot"], details["created"][0]))

    def _drain(self):
        progress = True
        while progress:
            progress = False
            for index, pair in enumerate(self.demand):
                if self.pending[index] and self.inventory.buffers[pair]:
                    self.inventory.remove(self.inventory.oldest(pair, 1)[0], 0, "consumption")
                    self.pending[index] -= 1
                    self.done[index] += 1
                    progress = True

    def _settle(self):
        if not (self.no_shortcut or self.geodesic or self.asap):
            return self._reference_settle()
        return self._filtered_settle(self.no_shortcut, self.geodesic, self.asap)

    def _filtered_settle(self, forbid_physical_output, require_geodesic=False, asap=False):
        """Copy of the repository's settling loop with one optional extra filter.

        ``check_copy`` verifies that the copy agrees with the original when the
        filter is off.
        """
        inv = self.inventory
        while True:
            changed = False
            for pivot in inv.nodes:
                candidates = []
                partners = [node for node in inv.nodes if node != pivot
                            and len(inv.buffers[inv.pair(node, pivot)]) >= inv.D]
                for x, y in combinations(partners, 2):
                    pair = inv.pair(x, y)
                    if forbid_physical_output and pair in inv.physical_edges:
                        continue
                    if require_geodesic and (self.distance[x][y]
                                             != self.distance[x][pivot] + self.distance[pivot][y]):
                        continue
                    left = len(inv.buffers[inv.pair(x, pivot)])
                    right = len(inv.buffers[inv.pair(y, pivot)])
                    output = len(inv.buffers[pair])
                    # ``asap`` drops the count thresholds: any physically possible swap is taken.
                    preferred = asap or output + 1 <= min(left - inv.D, right - inv.D)
                    relaxed = (self.swap_policy in {"pressure_relaxed", "pressure_oriented"} and not preferred
                               and output <= min(left - inv.D, right - inv.D)
                               and self._under_pressure(pivot, pair))
                    if not (preferred or relaxed):
                        continue
                    input_ids = None
                    if self.swap_policy == "pressure_oriented":
                        input_ids = self._oriented_inputs(pivot, pair, require_pressure=relaxed)
                        if input_ids is None:
                            continue
                    candidates.append((output, inv.order[x], inv.order[y], pair, relaxed, input_ids))
                if candidates:
                    selected = min(candidates)
                    self._swap(pivot, selected[3], pressure_relaxed=selected[4], input_ids=selected[5])
                    changed = True
            if not changed:
                break
        self._drain()

    def restore(self, signature):
        self.inventory = Inventory(self.graph, self.memory, admission_policy="reserved")
        for endpoints, pairs in signature:
            for first, second in pairs:
                self.inventory._insert(endpoints, 0, None, {endpoints[0]: first, endpoints[1]: second})

    def signature(self):
        inv = self.inventory
        return tuple(sorted(
            (endpoints, tuple((inv.pairs[i].origins[endpoints[0]], inv.pairs[i].origins[endpoints[1]])
                              for i in sorted(ids)))
            for endpoints, ids in inv.buffers.items() if ids))

    def apply(self, signature, pending, event):
        """One event from a concrete state. Returns inventory, pending, completions."""
        self.restore(signature)
        self.pending, self.done = list(pending), [0] * len(self.demand)
        self.swap_log = []
        kind, pair = event
        if kind == "generate":
            self.inventory.generate(pair, 0, None)
        else:
            self.pending[self.demand.index(pair)] += 1
        self._settle()
        return self.signature(), tuple(self.pending), tuple(self.done)

    def events(self):
        return [("generate", edge) for edge in self.edges] + [("request", pair) for pair in self.demand]

    def successors(self, state):
        signature, pending = state
        for event in self.events():
            concrete = list(pending)
            capped = [count == CAP for count in pending]
            new_signature, new_pending, done = self.apply(signature, concrete, event)
            choices = []
            for index, count in enumerate(new_pending):
                if capped[index]:
                    # "At least CAP" before the event. One more request keeps it there.
                    arrivals = event == ("request", self.demand[index])
                    if count == 0:
                        # A longer true backlog might have consumed more pairs.
                        raise ArithmeticError("raise CAP: one event emptied a capped backlog")
                    low = CAP + arrivals - done[index]
                    choices.append(range(min(low, CAP), CAP + 1))
                else:
                    choices.append((min(count, CAP),))
            for abstract in product(*choices):
                yield event, (new_signature, tuple(abstract)), done


def explore(arm, limit=2_000_000):
    start = ((), (0,) * len(arm.demand))
    graph = nx.DiGraph()
    graph.add_node(start)
    parent = {start: None}
    frontier = deque([start])
    while frontier:
        state = frontier.popleft()
        for event, target, done in arm.successors(state):
            served = frozenset(i for i, count in enumerate(done) if count)
            if graph.has_edge(state, target):
                graph[state][target]["served"] |= served
            else:
                graph.add_edge(state, target, served=served)
            if target not in parent:
                parent[target] = (state, event)
                frontier.append(target)
                if len(parent) > limit:
                    raise MemoryError("state limit exceeded")
    return graph, parent


def witness(parent, state):
    path = []
    while parent[state] is not None:
        state, event = parent[state]
        path.append(event)
    return path[::-1]


def describe(signature):
    """Readable inventory. A qubit's origin is the neighbor it was generated toward."""
    parts = []
    for endpoints, pairs in signature:
        for first, second in pairs:
            own = first == endpoints[1] and second == endpoints[0]
            tag = "" if own else f"[slots {endpoints[0]}>{first},{endpoints[1]}>{second}]"
            parts.append(f"{endpoints[0]}{endpoints[1]}{tag}")
    return " ".join(parts) or "empty"


def analyse(arm):
    graph, parent = explore(arm)
    classes = list(nx.attracting_components(graph))
    inventories = {state[0] for state in graph}
    summary = {"states": graph.number_of_nodes(), "inventories": len(inventories), "closed_classes": []}
    for component in classes:
        served = set()
        for state in component:
            for target, data in graph[state].items():
                if target in component:
                    served |= data["served"]
        signatures = sorted({state[0] for state in component})
        first = min(component, key=lambda s: len(witness(parent, s)))
        entry = {"states": len(component), "inventories": len(signatures),
                 "served": [list(arm.demand[i]) for i in sorted(served)],
                 "starved": [list(pair) for i, pair in enumerate(arm.demand) if i not in served],
                 "frozen": len(signatures) == 1 and not served,
                 "example": describe(signatures[0]),
                 "witness": [f"{'g' if kind == 'generate' else 'r'}{pair[0]}{pair[1]}"
                             for kind, pair in witness(parent, first)]}
        summary["closed_classes"].append(entry)
    dead = [c for c in summary["closed_classes"] if not c["served"]]
    partial = [c for c in summary["closed_classes"] if c["served"] and c["starved"]]
    live = [c for c in summary["closed_classes"] if not c["starved"]]
    summary["verdict"] = ("no lockup" if not dead and not partial else
                          "dead classes only" if dead and not live and not partial else
                          "lockup reachable")
    # Does a class that starves some demand remain reachable from every state?
    bad = set().union(*(c for c, info in zip(classes, summary["closed_classes"]) if info["starved"])) if classes else set()
    if bad:
        reach = set(bad)
        reverse = graph.reverse(copy=False)
        frontier = deque(bad)
        while frontier:
            for source in reverse[frontier.popleft()]:
                if source not in reach:
                    reach.add(source)
                    frontier.append(source)
        summary["lockup_reachable_from_every_state"] = len(reach) == graph.number_of_nodes()
    summary["frozen_inventories"] = sorted({c["example"] for c in dead if c["frozen"]})
    return summary, graph, parent


def check_copy(arm, graph):
    """The filtered settling loop with its filter off must equal the original."""
    events = arm.events()
    for signature, pending in graph:
        concrete = [min(count, CAP) for count in pending]
        for event in events:
            expected = arm.apply(signature, concrete, event)
            arm.restore(signature)
            arm.pending, arm.done = list(concrete), [0] * len(arm.demand)
            kind, pair = event
            if kind == "generate":
                arm.inventory.generate(pair, 0, None)
            else:
                arm.pending[arm.demand.index(pair)] += 1
            arm._filtered_settle(False)
            if expected != (arm.signature(), tuple(arm.pending), tuple(arm.done)):
                raise AssertionError("copied settling loop disagrees with the repository policy")


def check_against_simulator(topology, memory, policy, samples=200, length=40, seed=20261125):
    """Random event words through this driver and through the public simulator."""
    edges, demand = TOPOLOGIES[topology]
    if len(demand) != 1:
        raise ValueError("the public simulator comparison needs a single demand class")
    rng = random.Random(seed)
    arm = Arm(edges, demand, memory, policy)
    for _ in range(samples):
        word = [rng.choice(arm.events()) for _ in range(length)]
        signature, pending, completed = (), [0], 0
        for event in word:
            signature, pending, done = arm.apply(signature, pending, event)
            pending = list(pending)
            completed += done[0]
        nx.set_edge_attributes(arm.graph, 1.0, "generation_capacity")
        result = run_simulation(arm.graph, {demand[0]: 1.0}, memory_slots=memory, swap_policy=policy,
                                horizon=length + 2, ticks_per_time_unit=1,
                                trace=[{"kind": kind, "endpoints": pair, "time": i + 1}
                                       for i, (kind, pair) in enumerate(word)])
        live = sorted((tuple(item["endpoints"]),
                       tuple(sorted((o["node"], o["neighbor"]) for o in item["origins"])))
                      for item in result["live_pairs"])
        mine = sorted((endpoints, tuple(sorted(zip(endpoints, origins))))
                      for endpoints, pairs in signature for origins in pairs)
        if live != mine or result["completed_requests"] != completed or result["unserved_requests"] != pending[0]:
            raise AssertionError(f"driver disagrees with the simulator on {word}")
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topology", choices=sorted(TOPOLOGIES))
    parser.add_argument("--memory", type=int, nargs="+", default=[2, 3, 4])
    parser.add_argument("--layouts", nargs="+", default=[],
                        help="per-node budgets in node order, for example 2,3,2")
    parser.add_argument("--policies", nargs="+", default=["pressure_relaxed", "pressure_oriented"])
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--geodesic", action="store_true")
    parser.add_argument("--check", action="store_true", help="also run the two self-checks")
    parser.add_argument("--all-rules", action="store_true",
                        help="compact verdicts for the five swap rules in RULES")
    args = parser.parse_args()
    edges, demand = TOPOLOGIES[args.topology]
    rows = []
    if args.all_rules:
        layouts = [tuple(int(v) for v in layout.split(",")) for layout in args.layouts] or args.memory
        for memory in layouts:
            for name, (policy, no_shortcut, geodesic) in RULES.items():
                summary, _, _ = analyse(Arm(edges, demand, memory, policy,
                                            no_shortcut=no_shortcut, geodesic=geodesic))
                classes = summary["closed_classes"]
                print(json.dumps({
                    "topology": args.topology, "memory": memory, "rule": name, "verdict": summary["verdict"],
                    "states": summary["states"], "inventories": summary["inventories"],
                    "dead_classes": sum(not c["served"] for c in classes),
                    "partly_starved_classes": sum(bool(c["served"]) and bool(c["starved"]) for c in classes),
                    "lockup_reachable_from_every_state": summary.get("lockup_reachable_from_every_state"),
                    "frozen_examples": summary["frozen_inventories"][:3]}), flush=True)
        return
    budgets = [tuple(int(v) for v in layout.split(",")) for layout in args.layouts] or args.memory
    for memory in budgets:
        for policy in args.policies:
            arm = Arm(edges, demand, memory, policy, no_shortcut=args.no_shortcut, geodesic=args.geodesic)
            summary, graph, _ = analyse(arm)
            if args.check:
                check_copy(Arm(edges, demand, memory, policy), graph)
                if len(demand) == 1 and not (args.no_shortcut or args.geodesic):
                    summary["simulator_words_checked"] = check_against_simulator(args.topology, memory, policy)
            rows.append({"topology": args.topology, "memory": memory, "policy": policy,
                         "no_shortcut": args.no_shortcut, "geodesic": args.geodesic, **summary})
            print(json.dumps(rows[-1]), flush=True)


if __name__ == "__main__":
    main()

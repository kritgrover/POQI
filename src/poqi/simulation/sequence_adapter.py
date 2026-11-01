"""Finite slots and inherited cutoffs driven by SeQUeNCe Timeline events.

This is an inventory abstraction, not an optical/fidelity simulation. Successful
generation and requests are independent Poisson processes in declared abstract
time units; swaps are perfect, instantaneous, and run to local quiescence.
"""

from collections import Counter, deque
from dataclasses import dataclass
from itertools import combinations
import inspect
import math
import random
from pathlib import Path

from .inventory import Inventory


@dataclass
class SimulationResult:
    data: dict

    def to_dict(self):
        return self.data

    def __getitem__(self, key):
        return self.data[key]


def _positive(value, name, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")
    return float(value)


class _SequenceSimulation:
    priorities = {"expire": 0, "generate": 1, "swap": 2, "request": 3, "finish": 4}

    def __init__(self, graph, demand_rate, *, memory_slots, cutoff_time,
                 distillation_pairs, horizon, seed, ticks_per_time_unit,
                 time_unit, swap_policy, admission_policy, request_regime,
                 initial_pairs, trace, record_events):
        # Keep SeQUeNCe optional for LP-only imports and commands.
        from sequence.kernel.event import Event
        from sequence.kernel.process import Process
        from sequence.kernel.timeline import Timeline

        self.Event, self.Process = Event, Process
        self.source_path = inspect.getfile(Timeline)
        self.inventory = Inventory(graph, memory_slots, admission_policy=admission_policy,
                                   distillation_pairs=distillation_pairs)
        self.horizon = _positive(horizon, "horizon")
        if isinstance(ticks_per_time_unit, bool) or not isinstance(ticks_per_time_unit, int) or ticks_per_time_unit < 1:
            raise ValueError("ticks_per_time_unit must be a positive integer")
        self.ticks = ticks_per_time_unit
        self.end_tick = self._exact_tick(self.horizon, "horizon")
        if self.end_tick < 1:
            raise ValueError("horizon must resolve to an integer timeline tick")
        self.cutoff = None if cutoff_time is None else _positive(cutoff_time, "cutoff_time")
        self.cutoff_ticks = None if self.cutoff is None else self._exact_tick(self.cutoff, "cutoff_time")
        if self.cutoff_ticks is not None and self.cutoff_ticks < 1:
            raise ValueError("cutoff_time must resolve to a positive integer timeline tick")
        if not isinstance(time_unit, str) or not time_unit.strip():
            raise ValueError("time_unit must be a nonempty label")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if swap_policy not in {"balancing", "physical", "none"}:
            raise ValueError("swap_policy must be balancing, physical, or none")
        if request_regime != "offered":
            raise ValueError("request_regime must be offered (explicit unbounded request FIFO)")
        self.swap_policy, self.time_unit, self.seed = swap_policy, time_unit, seed
        self.admission_policy = admission_policy
        self.record_events = record_events
        self.timeline = Timeline(stop_time=self.end_tick + 1)
        self.timeline.show_progress = False
        self.serial = 0
        self.events = []
        self.queue = deque()
        self.offered = Counter()
        self.completed = Counter()
        self.latencies = []
        self.latencies_by_pair = {}
        self.counters = Counter()
        self.rejections = Counter()
        self.request_id = 0
        self.max_backlog = 0
        self.initial_count = 0
        self.demand = self._normalize_demand(demand_rate)
        self.generation = {}
        for u, v, attributes in graph.edges(data=True):
            if "generation_capacity" not in attributes:
                raise ValueError("every physical link needs generation_capacity")
            self.generation[self.inventory.pair(u, v)] = _positive(attributes["generation_capacity"], "generation_capacity", allow_zero=True)
        self._load_initial(initial_pairs)
        if trace is None:
            self._schedule_poisson_inputs()
        else:
            self._schedule_trace(trace)
        self._schedule(self.end_tick, "finish")

    def _exact_tick(self, value, label):
        scaled = value * self.ticks
        if not math.isfinite(scaled):
            raise ValueError(f"{label} exceeds the supported timeline range")
        tick = round(scaled)
        # Relative tolerance grows with absolute simulation time and can admit
        # fractions of whole ticks at long horizons. Keep rounding tolerance
        # below one millionth of a tick, independent of the absolute timestamp.
        tolerance = min(1e-12, 1e-6 / self.ticks)
        if not math.isclose(tick / self.ticks, value, rel_tol=0, abs_tol=tolerance):
            raise ValueError(f"{label} must resolve to an integer timeline tick")
        return tick

    def _normalize_demand(self, rates):
        if not isinstance(rates, dict):
            raise ValueError("demand_rate must map endpoint pairs to rates")
        answer = {}
        for endpoints, rate in rates.items():
            if not isinstance(endpoints, (tuple, list)) or len(endpoints) != 2:
                raise ValueError("demand_rate keys must be endpoint pairs")
            pair = self.inventory.pair(*endpoints)
            if pair in answer:
                raise ValueError("duplicate reversed demand pair")
            answer[pair] = _positive(rate, "demand_rate", allow_zero=True)
        return answer

    def _schedule(self, tick, kind, *args):
        if tick > self.end_tick:
            return
        priority = (self.priorities[kind], self.serial)
        self.serial += 1
        self.timeline.schedule(self.Event(tick, self.Process(self, "dispatch", [kind, *args]), priority=priority))

    def _schedule_expiry(self, item):
        if item.deadline is not None:
            self._schedule(item.deadline, "expire", item.identifier)

    def _load_initial(self, initial_pairs):
        if initial_pairs is None:
            return
        if isinstance(initial_pairs, dict):
            entries = [{"endpoints": list(pair), "count": count} for pair, count in initial_pairs.items()]
        else:
            entries = initial_pairs
        for entry in entries:
            pair = self.inventory.pair(*entry["endpoints"])
            count = entry.get("count", 1)
            age = _positive(entry.get("age", 0), "initial pair age", allow_zero=True)
            if age != 0:
                raise ValueError("initial_pairs currently require age=0; aged initial inventory needs explicit lineage")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("initial pair count must be a nonnegative integer")
            for _ in range(count):
                item, reason = self.inventory.generate(pair, 0, self.cutoff_ticks)
                if reason:
                    raise ValueError(f"initial_pairs violate {reason}")
                self.initial_count += 1
                self._schedule_expiry(item)
                self._log("initial", created=[self._pair_record(item)])

    def _schedule_poisson_inputs(self):
        # Stream identity is independent of memory/admission decisions. Reusing
        # a seed on a fixed graph+demand yields the same realized exogenous input.
        streams = [("generate", pair, rate) for pair, rate in self.generation.items()]
        streams += [("request", pair, rate) for pair, rate in self.demand.items()]
        for index, (kind, pair, rate) in enumerate(streams):
            if rate == 0:
                continue
            rng = random.Random((self.seed + 1) * 1000003 + index)
            moment = rng.expovariate(rate)
            while moment < self.horizon:
                tick = round(moment * self.ticks)
                if tick < self.end_tick:
                    self._schedule(tick, kind, pair, 1)
                moment += rng.expovariate(rate)

    def _schedule_trace(self, trace):
        for entry in trace:
            moment = _positive(entry["time"], "trace time", allow_zero=True)
            tick = self._exact_tick(moment, "trace time")
            if tick >= self.end_tick:
                raise ValueError("trace times must resolve to ticks and lie in [0, horizon)")
            kind = entry["kind"]
            if kind not in {"generate", "request", "swap"}:
                raise ValueError("trace kind must be generate, request, or swap")
            pair = self.inventory.pair(*entry["endpoints"])
            count = entry.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError("trace count must be a positive integer")
            if kind == "generate" and pair not in self.generation:
                raise ValueError("generation trace requires physical edge")
            if kind == "request" and pair not in self.demand:
                raise ValueError("request trace pair must be declared in demand_rate")
            if kind == "swap":
                pivot = entry["pivot"]
                if pivot not in self.inventory.order or pivot in pair:
                    raise ValueError("swap trace pivot must be a third known node")
                self._schedule(tick, kind, pair, count, pivot)
            else:
                self._schedule(tick, kind, pair, count)

    @staticmethod
    def _pair_record(item):
        return {"id": item.identifier, "endpoints": list(item.endpoints),
                "admitted_tick": item.admitted, "deadline_tick": item.deadline,
                "parents": list(item.parents),
                "origins": [{"node": node, "neighbor": neighbor} for node, neighbor in item.origins.items()]}

    def _log(self, kind, **details):
        if self.record_events:
            self.events.append({"kind": kind, "tick": self.timeline.now(),
                                "time": self.timeline.now() / self.ticks,
                                "occupancy": [{"node": n, "slots": self.inventory.occupancy[n]} for n in self.inventory.nodes],
                                "queue_length": len(self.queue), **details})

    def _swap(self, pivot, pair):
        output, removed = self.inventory.swap(pivot, pair, self.timeline.now())
        if output is None:
            return False
        self.counters["swaps"] += 1
        self._schedule_expiry(output)
        self._log("swap", pivot=pivot, removed=removed, created=[self._pair_record(output)])
        return True

    def _drain(self):
        D = self.inventory.D
        while self.queue:
            identifier, pair, arrived = self.queue[0]
            if len(self.inventory.buffers[pair]) < D:
                break
            removed = self.inventory.oldest(pair, D)
            for item_id in removed:
                self.inventory.remove(item_id, self.timeline.now(), "consumption")
            self.queue.popleft()
            self.completed[pair] += 1
            latency = (self.timeline.now() - arrived) / self.ticks
            self.latencies.append(latency)
            self.latencies_by_pair.setdefault(pair, []).append(latency)
            self._log("complete", request_id=identifier, endpoints=list(pair), removed=removed, latency=latency)

    def _settle(self):
        if self.swap_policy != "none":
            while True:
                changed = False
                for pivot in self.inventory.nodes:
                    candidates = []
                    partners = [node for node in self.inventory.nodes if node != pivot
                                and len(self.inventory.buffers[self.inventory.pair(node, pivot)]) >= self.inventory.D]
                    for x, y in combinations(partners, 2):
                        pair = self.inventory.pair(x, y)
                        left = len(self.inventory.buffers[self.inventory.pair(x, pivot)])
                        right = len(self.inventory.buffers[self.inventory.pair(y, pivot)])
                        output = len(self.inventory.buffers[pair])
                        preferred = output + 1 <= min(left - self.inventory.D, right - self.inventory.D)
                        if self.swap_policy == "balancing" and not preferred:
                            self.counters["heuristic_refusals"] += 1
                            continue
                        candidates.append((output, self.inventory.order[x], self.inventory.order[y], pair))
                    if candidates:
                        self._swap(pivot, min(candidates)[-1])
                        changed = True
                if not changed:
                    break
        self._drain()

    def dispatch(self, kind, *args):
        now = self.timeline.now()
        self.inventory.advance(now)
        if kind == "finish":
            self._log("finish")
            return
        if kind == "expire":
            identifier = args[0]
            item = self.inventory.pairs.get(identifier)
            if item is None:
                self.counters["stale_expiry_events"] += 1
                return
            if item.deadline != now:
                raise AssertionError("expiry event does not match pair deadline")
            # Purge every pair due now before settling. Otherwise the first
            # expiry callback could swap a different pair whose same-time
            # expiry callback has not run yet.
            due = [pair.identifier for pair in self.inventory.pairs.values()
                   if pair.deadline is not None and pair.deadline <= now]
            for expired_id in due:
                self.inventory.remove(expired_id, now, "expiry")
                self.counters["expired_pairs"] += 1
                self._log("expire", removed=[expired_id])
        elif kind == "generate":
            pair, count = args
            for _ in range(count):
                self.counters["offered_generation"] += 1
                deadline = None if self.cutoff_ticks is None else now + self.cutoff_ticks
                item, reason = self.inventory.generate(pair, now, deadline)
                if reason:
                    self.rejections[reason] += 1
                    self._log("reject", endpoints=list(pair), reason=reason)
                else:
                    self.counters["admitted_generation"] += 1
                    self._schedule_expiry(item)
                    self._log("generate", created=[self._pair_record(item)])
        elif kind == "request":
            pair, count = args
            for _ in range(count):
                self.queue.append((self.request_id, pair, now))
                self.offered[pair] += 1
                self._log("request", request_id=self.request_id, endpoints=list(pair))
                self.request_id += 1
            self.max_backlog = max(self.max_backlog, len(self.queue))
        elif kind == "swap":
            pair, count, pivot = args
            for _ in range(count):
                if not self._swap(pivot, pair):
                    self.counters["infeasible_swap_attempts"] += 1
        # The observation interval is [0, horizon). Boundary expiry establishes
        # which pairs remain alive, but must not trigger new swaps or service
        # outside that interval.
        if now < self.end_tick:
            self._settle()
        self._check_conservation()

    def _check_conservation(self):
        expected = (self.initial_count + self.counters["admitted_generation"]
                    - (2 * self.inventory.D - 1) * self.counters["swaps"]
                    - self.inventory.D * sum(self.completed.values()) - self.counters["expired_pairs"])
        if len(self.inventory.pairs) != expected:
            raise AssertionError("pair conservation failed")
        if self.counters["offered_generation"] != self.counters["admitted_generation"] + sum(self.rejections.values()):
            raise AssertionError("generation admission accounting failed")
        self.inventory.validate()

    def run(self):
        self.timeline.init()
        self.timeline.run()
        self._check_conservation()
        inv = self.inventory
        episodes = []
        total_area = sum(inv.pair_area.values())
        total_residence = 0
        for pair in combinations(inv.nodes, 2):
            censored = sum(self.end_tick - inv.pairs[i].admitted for i in inv.buffers[pair])
            residence = inv.departed_residence[pair] + censored
            total_residence += residence
            if not math.isclose(inv.pair_area[pair], residence, abs_tol=1e-6):
                raise AssertionError("episode residence and occupancy integral disagree")
            arrivals, departures = inv.episode_arrivals[pair], inv.episode_departures[pair]
            episodes.append({"endpoints": list(pair), "arrivals": arrivals, "departures": departures,
                             "censored_episodes": len(inv.buffers[pair]),
                             "departed_residence_sum": inv.departed_residence[pair] / self.ticks,
                             "censored_residence_sum": censored / self.ticks,
                             "completed_episode_mean": inv.departed_residence[pair] / (self.ticks * departures) if departures else None,
                             "window_restricted_mean": residence / (self.ticks * arrivals) if arrivals else None,
                             "pair_occupancy_integral": inv.pair_area[pair] / self.ticks})
        service = []
        for pair, demand in self.demand.items():
            latencies = self.latencies_by_pair.get(pair, [])
            service.append({"endpoints": list(pair), "demand_rate": demand,
                            "offered_requests": self.offered[pair], "completed_requests": self.completed[pair],
                            "unserved_requests": self.offered[pair] - self.completed[pair],
                            "throughput": self.completed[pair] / self.horizon,
                            "offered_rate_satisfaction": self.completed[pair] / (self.horizon * demand) if demand else None,
                            "mean_completed_latency": sum(latencies) / len(latencies) if latencies else None})
        completed = sum(self.completed.values())
        offered = sum(self.offered.values())
        occupancy = [{"node": node, "memory_slots": inv.limits[node],
                      "mean": inv.area[node] / (self.ticks * self.horizon),
                      "peak": inv.peak_occupancy[node], "final": inv.occupancy[node],
                      "integral": inv.area[node] / self.ticks} for node in inv.nodes]
        return SimulationResult({
            "status": "completed", "backend": "sequence", "sequence_source": self.source_path,
            "model": "abstract-pair-inventory", "loss_model": "lossless" if self.cutoff is None else "inherited-hard-cutoff",
            "time_unit": self.time_unit, "ticks_per_time_unit": self.ticks, "horizon": self.horizon,
            "timeline_final_tick": self.timeline.now(), "timeline_run_counter": self.timeline.run_counter,
            "timeline_schedule_counter": self.timeline.schedule_counter, "seed": self.seed,
            "cutoff_time": self.cutoff, "distillation_pairs": inv.D,
            "swap_policy": self.swap_policy, "admission_policy": self.admission_policy,
            "request_regime": "offered-unbounded-global-fifo", "warmup": 0,
            "scheduling": "expiry, generation, explicit swap, request; automatic swap-to-quiescence then FIFO after each event before horizon",
            "rounding": "Poisson arrival times rounded to nearest timeline tick; horizon arrivals excluded",
            "initial_pairs": self.initial_count, "remaining_pairs": len(inv.pairs),
            "offered_generation": self.counters["offered_generation"], "admitted_generation": self.counters["admitted_generation"],
            "admission_rejections": sum(self.rejections.values()), "rejections_by_reason": dict(self.rejections),
            "expired_pairs": self.counters["expired_pairs"], "swaps": self.counters["swaps"],
            "heuristic_refusals": self.counters["heuristic_refusals"],
            "infeasible_swap_attempts": self.counters["infeasible_swap_attempts"],
            "stale_expiry_events": self.counters["stale_expiry_events"],
            "offered_requests": offered, "completed_requests": completed, "unserved_requests": len(self.queue),
            "maximum_backlog": self.max_backlog, "backlog_growth_rate": len(self.queue) / self.horizon,
            "throughput": completed / self.horizon,
            "mean_completed_latency": sum(self.latencies) / completed if completed else None,
            "latency_interpretation": "completed requests only, censored backlog retained; no stationarity claim",
            "service_by_pair": service, "occupancy_by_node": occupancy,
            "reservations": [{"node": node, "neighbors": [{"neighbor": neighbor, "slots": quota} for neighbor, quota in quotas.items()]} for node, quotas in inv.quotas.items()],
            "residence_by_pair": episodes,
            "occupancy_episode_residual": (total_area - total_residence) / self.ticks,
            "pair_conservation_residual": 0,
            "live_pairs": [self._pair_record(item) for item in inv.pairs.values()],
            "unserved_queue": [{"id": identifier, "endpoints": list(pair), "arrival_tick": arrived, "age": (self.end_tick - arrived) / self.ticks} for identifier, pair, arrived in self.queue],
            "events": self.events,
        })


def run_simulation(graph, demand_rate, *, memory_slots=None, cutoff_time=None,
                   distillation_pairs=1, horizon=100.0, seed=0,
                   ticks_per_time_unit=1000000, time_unit="abstract",
                   swap_policy="balancing", admission_policy="reserved",
                   request_regime="offered", initial_pairs=None, trace=None,
                   record_events=True):
    """Run real SeQUeNCe events with hard slots and optional inherited expiry.

    ``trace`` replaces Poisson input with explicit events of the form
    ``{time, kind, endpoints, count?}``; explicit ``swap`` also takes ``pivot``
    and attempts a physically feasible swap independent of automatic policy.
    Set ``swap_policy='none'`` when testing an entirely explicit trace.
    ``initial_pairs`` accepts physical-edge counts or zero-age entry records.
    Every run observes [0, horizon); expiries at horizon are processed before
    the finish marker so final inventory is alive at the observation boundary.
    """
    return _SequenceSimulation(graph, demand_rate, memory_slots=memory_slots,
                               cutoff_time=cutoff_time, distillation_pairs=distillation_pairs,
                               horizon=horizon, seed=seed, ticks_per_time_unit=ticks_per_time_unit,
                               time_unit=time_unit, swap_policy=swap_policy,
                               admission_policy=admission_policy, request_regime=request_regime,
                               initial_pairs=initial_pairs, trace=trace,
                               record_events=record_events).run()


def sequence_smoke():
    """Verify root-local SeQUeNCe provenance and execute a real timed event."""
    import networkx as nx

    graph = nx.path_graph(2)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    result = run_simulation(graph, {(0, 1): 1.0}, horizon=2.0,
                            ticks_per_time_unit=1000,
                            trace=[{"time": 0.5, "kind": "generate", "endpoints": [0, 1]},
                                   {"time": 1.0, "kind": "request", "endpoints": [0, 1]}]).to_dict()
    expected = Path(__file__).resolve().parents[3] / "SeQUeNCe" / "sequence" / "kernel" / "timeline.py"
    # parents[3] is src/poqi/simulation -> repository root.
    source = Path(result["sequence_source"]).resolve()
    if source != expected.resolve():
        raise RuntimeError(f"SeQUeNCe must resolve to {expected}; found {source}")
    if result["timeline_final_tick"] != 2000 or result["completed_requests"] != 1:
        raise AssertionError("SeQUeNCe smoke event did not execute correctly")
    return {"status": "passed", "sequence_source": str(source),
            "timeline_final_tick": result["timeline_final_tick"],
            "timeline_run_counter": result["timeline_run_counter"],
            "completed_requests": result["completed_requests"],
            "time_unit": result["time_unit"],
            "ticks_per_time_unit": result["ticks_per_time_unit"]}

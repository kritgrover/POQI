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


class _Gaps:
    """Intervals with a request waiting and no completion, for one class of requests.

    Arrivals do not restart an interval. A completion ends it and starts the
    next one if a request is still waiting. Lengths are clipped to the window,
    and the interval still open at the horizon counts with its observed length.
    """

    def __init__(self, start_tick, end_tick, ticks, threshold):
        self.start_tick, self.end_tick, self.ticks = start_tick, end_tick, ticks
        self.threshold = None if threshold is None else threshold * ticks
        self.pending = 0
        self.opened = None
        self.lengths = []

    def arrival(self, tick):
        if self.pending == 0:
            self.opened = tick
        self.pending += 1

    def departure(self, tick):
        if tick > self.start_tick:
            self.lengths.append(tick - max(self.opened, self.start_tick))
        self.pending -= 1
        self.opened = tick if self.pending else None

    def summary(self):
        lengths = list(self.lengths)
        trailing = None
        if self.opened is not None:
            trailing = self.end_tick - max(self.opened, self.start_tick)
            lengths.append(trailing)
        window = self.end_tick - self.start_tick
        answer = {"interruptions": len(lengths),
                  "interrupted_time": sum(lengths) / self.ticks,
                  "interrupted_fraction": sum(lengths) / window,
                  "longest_interruption": max(lengths, default=0) / self.ticks,
                  "mean_interruption": sum(lengths) / (len(lengths) * self.ticks) if lengths else None,
                  "trailing_interruption": None if trailing is None else trailing / self.ticks,
                  "right_censored": trailing is not None}
        if self.threshold is not None:
            long = [length for length in lengths if length >= self.threshold]
            answer.update(outages=len(long), outage_time=sum(long) / self.ticks,
                          outage_fraction=sum(long) / window)
        return answer


class _SequenceSimulation:
    priorities = {"expire": 0, "generate": 1, "swap": 2, "request": 3, "finish": 4}

    def __init__(self, graph, demand_rate, *, memory_slots, cutoff_time,
                 distillation_pairs, horizon, seed, ticks_per_time_unit,
                 time_unit, swap_policy, admission_policy, request_regime,
                 initial_pairs, trace, record_events, recovery_policy="none",
                 stuck_patience=0.0, service_order="fifo", measure_from=0.0,
                 outage_threshold=None):
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
        if swap_policy not in {"balancing", "pressure_relaxed", "pressure_oriented", "physical", "none"}:
            raise ValueError("swap_policy must be balancing, pressure_relaxed, pressure_oriented, physical, or none")
        if swap_policy == "pressure_oriented" and distillation_pairs != 1:
            raise ValueError("pressure_oriented requires distillation_pairs=1")
        if request_regime != "offered":
            raise ValueError("request_regime must be offered (explicit unbounded request FIFO)")
        if recovery_policy not in {"none", "drop_when_stuck"}:
            raise ValueError("recovery_policy must be none or drop_when_stuck")
        if service_order not in {"fifo", "per_pair"}:
            raise ValueError("service_order must be fifo or per_pair")
        self.recovery_policy, self.service_order = recovery_policy, service_order
        self.stuck_patience = _positive(stuck_patience, "stuck_patience", allow_zero=True)
        self.patience_ticks = self._exact_tick(self.stuck_patience, "stuck_patience")
        self.measure_from = _positive(measure_from, "measure_from", allow_zero=True)
        self.window_tick = self._exact_tick(self.measure_from, "measure_from")
        if self.window_tick >= self.end_tick:
            raise ValueError("measure_from must be earlier than horizon")
        self.outage_threshold = (None if outage_threshold is None
                                 else _positive(outage_threshold, "outage_threshold"))
        self.swap_policy, self.time_unit, self.seed = swap_policy, time_unit, seed
        self.admission_policy = admission_policy
        self.record_events = record_events
        self.timeline = Timeline(stop_time=self.end_tick + 1)
        self.timeline.show_progress = False
        self.serial = 0
        self.events = []
        self.queue = deque()
        self.waiting = {}
        self.backlog = 0
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
        # Interruption clocks: one per demand pair and one (key None) for all pairs.
        self.gaps = {key: _Gaps(self.window_tick, self.end_tick, self.ticks, self.outage_threshold)
                     for key in (None, *self.demand)}
        self.window_offered = Counter()
        self.window_completed = Counter()
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
                                "queue_length": self.backlog, **details})

    def _under_pressure(self, pivot, pair, input_ids=None):
        """Would these inputs release a full pivot or a full positive origin quota?"""
        inv = self.inventory
        limit = inv.limits[pivot]
        if limit is None:
            return False
        if inv.occupancy[pivot] >= limit:
            return True
        if self.admission_policy == "reserved":
            if input_ids is None:
                input_ids = (identifier for partner in pair
                             for identifier in inv.oldest(inv.pair(pivot, partner), inv.D))
            for identifier in input_ids:
                origin = inv.pairs[identifier].origins[pivot]
                quota = inv.quotas[pivot][origin]
                if quota > 0 and inv.origin_occupancy[pivot, origin] >= quota:
                    return True
        return False

    def _oriented_inputs(self, pivot, pair, require_pressure):
        """First eligible two-qubit input in the ordinary deadline/age/ID order."""
        inv = self.inventory
        oldest_by_origin = []
        for partner in pair:
            # Eligibility depends only on the two origins, so a later pair of
            # the same origin can never precede its first eligible representative.
            first = {}
            for identifier in inv.oldest(inv.pair(pivot, partner)):
                first.setdefault(inv.pairs[identifier].origins[pivot], identifier)
            oldest_by_origin.append(first)
        for left_origin, left_id in oldest_by_origin[0].items():
            for right_origin, right_id in oldest_by_origin[1].items():
                if left_origin == right_origin:
                    continue
                input_ids = (left_id, right_id)
                if not require_pressure or self._under_pressure(pivot, pair, input_ids):
                    return input_ids
        return None

    def _swap(self, pivot, pair, *, pressure_relaxed=False, input_ids=None):
        if self.swap_policy == "pressure_oriented" and input_ids is None:
            # Explicit trace swaps also respect this policy's physical-origin restriction.
            input_ids = self._oriented_inputs(pivot, pair, require_pressure=False)
            if input_ids is None:
                return False
        output, removed = self.inventory.swap(pivot, pair, self.timeline.now(), input_ids=input_ids)
        if output is None:
            return False
        self.counters["swaps"] += 1
        if pressure_relaxed:
            self.counters["pressure_relaxed_swaps"] += 1
        self._schedule_expiry(output)
        details = {"pressure_relaxed": True} if pressure_relaxed else {}
        self._log("swap", pivot=pivot, removed=removed, created=[self._pair_record(output)], **details)
        return True

    def _complete(self, queue):
        now = self.timeline.now()
        identifier, pair, arrived = queue.popleft()
        removed = self.inventory.oldest(pair, self.inventory.D)
        for item_id in removed:
            self.inventory.remove(item_id, now, "consumption")
        self.backlog -= 1
        self.completed[pair] += 1
        if now >= self.window_tick:
            self.window_completed[pair] += 1
        latency = (now - arrived) / self.ticks
        self.latencies.append(latency)
        self.latencies_by_pair.setdefault(pair, []).append(latency)
        self.gaps[pair].departure(now)
        self.gaps[None].departure(now)
        self._log("complete", request_id=identifier, endpoints=list(pair), removed=removed, latency=latency)

    def _drain(self):
        D = self.inventory.D
        if self.service_order == "per_pair":
            # Each demand pair is its own FIFO; a waiting pair never holds back another.
            for pair, queue in self.waiting.items():
                while queue and len(self.inventory.buffers[pair]) >= D:
                    self._complete(queue)
            return
        while self.queue and len(self.inventory.buffers[self.queue[0][1]]) >= D:
            self._complete(self.queue)

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
                        # First use the original policy's oldest inputs to determine
                        # partner-pair eligibility, even if the guard must replace one.
                        relaxed = (self.swap_policy in {"pressure_relaxed", "pressure_oriented"} and not preferred
                                   and output <= min(left - self.inventory.D, right - self.inventory.D)
                                   and self._under_pressure(pivot, pair))
                        if self.swap_policy != "physical" and not (preferred or relaxed):
                            self.counters["heuristic_refusals"] += 1
                            continue
                        input_ids = None
                        if self.swap_policy == "pressure_oriented":
                            input_ids = self._oriented_inputs(pivot, pair, require_pressure=relaxed)
                            if input_ids is None:
                                self.counters["heuristic_refusals"] += 1
                                continue
                        candidates.append((output, self.inventory.order[x], self.inventory.order[y], pair, relaxed, input_ids))
                    if candidates:
                        selected = min(candidates)
                        self._swap(pivot, selected[3], pressure_relaxed=selected[4], input_ids=selected[5])
                        changed = True
                if not changed:
                    break
        self._drain()

    def _drop_and_generate(self, pair, now, deadline, reason):
        """Drop-when-stuck: evict what has blocked this link for at least the patience."""
        patience = self.patience_ticks
        victims = self.inventory.blocking_victims(pair, lambda item: now - item.admitted >= patience)
        if not victims:
            return None, reason
        for identifier in victims:
            self.inventory.remove(identifier, now, "stuck_drop")
        self.counters["stuck_drops"] += len(victims)
        self.counters["stuck_drop_events"] += 1
        self._log("drop", endpoints=list(pair), removed=victims, blocked_by=reason)
        item, reason = self.inventory.generate(pair, now, deadline)
        if reason:
            raise AssertionError("generation still blocked after dropping its blockers")
        return item, None

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
                if reason and self.recovery_policy == "drop_when_stuck":
                    item, reason = self._drop_and_generate(pair, now, deadline, reason)
                if reason:
                    self.rejections[reason] += 1
                    self._log("reject", endpoints=list(pair), reason=reason)
                else:
                    self.counters["admitted_generation"] += 1
                    self._schedule_expiry(item)
                    self._log("generate", created=[self._pair_record(item)])
        elif kind == "request":
            pair, count = args
            queue = self.queue if self.service_order == "fifo" else self.waiting.setdefault(pair, deque())
            for _ in range(count):
                queue.append((self.request_id, pair, now))
                self.backlog += 1
                self.offered[pair] += 1
                if now >= self.window_tick:
                    self.window_offered[pair] += 1
                self.gaps[pair].arrival(now)
                self.gaps[None].arrival(now)
                self._log("request", request_id=self.request_id, endpoints=list(pair))
                self.request_id += 1
            self.max_backlog = max(self.max_backlog, self.backlog)
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
                    - self.inventory.D * sum(self.completed.values()) - self.counters["expired_pairs"]
                    - self.counters["stuck_drops"])
        if len(self.inventory.pairs) != expected:
            raise AssertionError("pair conservation failed")
        if self.counters["offered_generation"] != self.counters["admitted_generation"] + sum(self.rejections.values()):
            raise AssertionError("generation admission accounting failed")
        self.inventory.validate()

    def _continuity(self):
        """Interruptions and starvation on the window [measure_from, horizon)."""
        window = self.horizon - self.measure_from
        rows = []
        for pair, demand in self.demand.items():
            gaps = self.gaps[pair].summary()
            done = self.window_completed[pair]
            rows.append({"endpoints": list(pair), "demand_rate": demand,
                         "offered_requests": self.window_offered[pair],
                         "completed_requests": done, "throughput": done / window,
                         "satisfaction": done / (window * demand) if demand else None,
                         "waiting_at_horizon": self.gaps[pair].pending,
                         # Something waited inside the window and nothing completed in it.
                         "starved": done == 0 and gaps["interrupted_time"] > 0, **gaps})
        ratios = [row["satisfaction"] for row in rows if row["satisfaction"] is not None]
        fairness = (sum(ratios) ** 2 / (len(ratios) * sum(r * r for r in ratios))
                    if any(ratios) else None)
        return {"window": [self.measure_from, self.horizon], "outage_threshold": self.outage_threshold,
                "definition": "interruption: a request of the class waits and none of that class completes; "
                              "lengths are clipped to the window and an unfinished one counts to the horizon",
                "all_pairs": self.gaps[None].summary(),
                "starved_pairs": sum(row["starved"] for row in rows),
                "minimum_satisfaction": min(ratios, default=None), "jain_fairness": fairness,
                "by_pair": rows}

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
        unserved = sorted(entry for queue in (self.queue, *self.waiting.values()) for entry in queue)
        if len(unserved) != self.backlog or offered - completed != self.backlog:
            raise AssertionError("request conservation failed")
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
            "request_regime": ("offered-unbounded-global-fifo" if self.service_order == "fifo"
                               else "offered-unbounded-per-pair-fifo"),
            "service_order": self.service_order, "warmup": 0,
            "recovery_policy": self.recovery_policy,
            **({"stuck_patience": self.stuck_patience, "stuck_drops": self.counters["stuck_drops"],
                "stuck_drop_events": self.counters["stuck_drop_events"]}
               if self.recovery_policy == "drop_when_stuck" else {}),
            "scheduling": "expiry, generation, explicit swap, request; automatic swap-to-quiescence then FIFO after each event before horizon",
            "rounding": "Poisson arrival times rounded to nearest timeline tick; horizon arrivals excluded",
            "initial_pairs": self.initial_count, "remaining_pairs": len(inv.pairs),
            "offered_generation": self.counters["offered_generation"], "admitted_generation": self.counters["admitted_generation"],
            "admission_rejections": sum(self.rejections.values()), "rejections_by_reason": dict(self.rejections),
            "expired_pairs": self.counters["expired_pairs"], "swaps": self.counters["swaps"],
            "heuristic_refusals": self.counters["heuristic_refusals"],
            **({"pressure_relaxed_swaps": self.counters["pressure_relaxed_swaps"]}
               if self.swap_policy in {"pressure_relaxed", "pressure_oriented"} else {}),
            "infeasible_swap_attempts": self.counters["infeasible_swap_attempts"],
            "stale_expiry_events": self.counters["stale_expiry_events"],
            "offered_requests": offered, "completed_requests": completed, "unserved_requests": self.backlog,
            "maximum_backlog": self.max_backlog, "backlog_growth_rate": self.backlog / self.horizon,
            "throughput": completed / self.horizon,
            "mean_completed_latency": sum(self.latencies) / completed if completed else None,
            "latency_interpretation": "completed requests only, censored backlog retained; no stationarity claim",
            "service_by_pair": service, "service_continuity": self._continuity(),
            "occupancy_by_node": occupancy,
            "reservations": [{"node": node, "neighbors": [{"neighbor": neighbor, "slots": quota} for neighbor, quota in quotas.items()]} for node, quotas in inv.quotas.items()],
            "residence_by_pair": episodes,
            "occupancy_episode_residual": (total_area - total_residence) / self.ticks,
            "pair_conservation_residual": 0,
            "live_pairs": [self._pair_record(item) for item in inv.pairs.values()],
            "unserved_queue": [{"id": identifier, "endpoints": list(pair), "arrival_tick": arrived, "age": (self.end_tick - arrived) / self.ticks} for identifier, pair, arrived in unserved],
            "events": self.events,
        })


def run_simulation(graph, demand_rate, *, memory_slots=None, cutoff_time=None,
                   distillation_pairs=1, horizon=100.0, seed=0,
                   ticks_per_time_unit=1000000, time_unit="abstract",
                   swap_policy="balancing", admission_policy="reserved",
                   request_regime="offered", initial_pairs=None, trace=None,
                   record_events=True, recovery_policy="none", stuck_patience=0.0,
                   service_order="fifo", measure_from=0.0, outage_threshold=None):
    """Run real SeQUeNCe events with hard slots and optional inherited expiry.

    ``trace`` replaces Poisson input with explicit events of the form
    ``{time, kind, endpoints, count?}``; explicit ``swap`` also takes ``pivot``
    and bypasses automatic count and pressure thresholds. The D=1
    ``pressure_oriented`` policy also requires the two selected pivot qubits
    to have different physical generation neighbors, including in explicit swaps.
    Set ``swap_policy='none'`` when testing an entirely explicit trace.
    ``initial_pairs`` accepts physical-edge counts or zero-age entry records.
    Every run observes [0, horizon); expiries at horizon are processed before
    the finish marker so final inventory is alive at the observation boundary.

    ``recovery_policy='drop_when_stuck'`` lets a blocked generation evict the
    pair that holds its slot, provided that pair is not an elementary pair of
    the same link and has been stored for at least ``stuck_patience``.
    ``service_order='per_pair'`` serves each demand pair from its own FIFO.
    ``service_continuity`` reports interruptions on [``measure_from``, horizon):
    intervals with a request waiting and no completion, per demand pair and
    for all pairs together. ``outage_threshold`` sets the length from which an
    interruption counts as an outage.
    """
    return _SequenceSimulation(graph, demand_rate, memory_slots=memory_slots,
                               cutoff_time=cutoff_time, distillation_pairs=distillation_pairs,
                               horizon=horizon, seed=seed, ticks_per_time_unit=ticks_per_time_unit,
                               time_unit=time_unit, swap_policy=swap_policy,
                               admission_policy=admission_policy, request_regime=request_regime,
                               initial_pairs=initial_pairs, trace=trace,
                               record_events=record_events, recovery_policy=recovery_policy,
                               stuck_patience=stuck_patience, service_order=service_order,
                               measure_from=measure_from, outage_threshold=outage_threshold).run()


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

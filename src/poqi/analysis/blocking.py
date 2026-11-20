"""Replay D=1 logs without changing dynamics; preserve physical slot lifetimes.

Pair episodes restart at swaps. An outer endpoint's physical slot does not:
its admission time and original generation neighbor follow the swap lineage.
Only zero-initial-inventory logs are supported. Arrival/cohort windows are
half-open; survivors are censored at the simulation horizon.
"""

from collections import Counter
from collections.abc import Hashable, Mapping
import hashlib
import json
import math


def _require(condition, message):
    if not condition:
        raise ValueError(message)


class _Group:
    def __init__(self, identity, capacity, start, cohort_end, end, ticks):
        self.identity, self.capacity = identity, capacity
        self.start, self.cohort_end, self.end, self.ticks = start, cohort_end, end, ticks
        self.count = self.last = self.area = self.departed = 0
        self.histogram = Counter()
        self.counters = Counter()

    def advance(self, tick):
        self.area += self.count * (tick - self.last)
        duration = max(0, min(tick, self.end) - max(self.last, self.start))
        self.histogram[self.count] += duration
        self.last = tick

    def attempt(self, tick, accepted, full, reserved):
        if self.start <= tick < self.end:
            self.counters.update(offered=1, accepted=int(accepted), local_full=int(full),
                                 local_reservation=int(reserved), local_unavailable=int(full or reserved))

    def admit(self, tick):
        self.count += 1
        if self.start <= tick < self.cohort_end:
            self.counters["cohort_arrivals"] += 1

    def depart(self, admitted, tick):
        self.count -= 1
        _require(self.count >= 0 and tick >= admitted, "invalid slot departure")
        self.departed += tick - admitted
        if self.start <= admitted < self.cohort_end:
            self.counters["cohort_departures"] += 1
            self.counters["cohort_departed_holding_sum"] += tick - admitted

    def result(self, survivors):
        self.advance(self.end)
        _require(len(survivors) == self.count, "survivor occupancy mismatch")
        censored = sum(self.end - admitted for admitted in survivors)
        _require(self.area == self.departed + censored, "physical slot area/lifetime mismatch")
        cohort_survivors = [t for t in survivors if self.start <= t < self.cohort_end]
        c = self.counters
        c["cohort_censored"] = len(cohort_survivors)
        c["cohort_censored_holding_sum"] = sum(self.end - t for t in cohort_survivors)
        _require(c["cohort_arrivals"] == c["cohort_departures"] + c["cohort_censored"],
                 "physical slot cohort count mismatch")
        duration = (self.end - self.start) / self.ticks
        occupancy_integral = sum(n * t for n, t in self.histogram.items()) / self.ticks
        result = {**self.identity, **{name: c[name] for name in
                  ("offered", "accepted", "local_full", "local_reservation", "local_unavailable",
                   "cohort_arrivals", "cohort_departures", "cohort_censored")},
                  "rejected": c["offered"] - c["accepted"],
                  "offered_rate": c["offered"] / duration, "accepted_rate": c["accepted"] / duration,
                  "occupancy_integral": occupancy_integral, "mean_occupancy": occupancy_integral / duration,
                  "full_run_occupancy_integral": self.area / self.ticks,
                  "full_run_holding_area_residual": 0.0,
                  "occupancy_distribution": [{"slots": n, "time": t / self.ticks,
                      "fraction": t / (self.end - self.start)} for n, t in sorted(self.histogram.items()) if t],
                  "full_time_fraction": (sum(t for n, t in self.histogram.items() if n >= self.capacity)
                      / (self.end - self.start)) if self.capacity is not None else None}
        for name in ("local_full", "local_reservation", "local_unavailable"):
            result[f"{name}_probability"] = c[name] / c["offered"] if c["offered"] else None
        for name in ("cohort_departed_holding_sum", "cohort_censored_holding_sum"):
            result[name] = c[name] / self.ticks
        observed = result["cohort_departed_holding_sum"] + result["cohort_censored_holding_sum"]
        result["cohort_restricted_mean"] = observed / c["cohort_arrivals"] if c["cohort_arrivals"] else None
        result["completed_holding_mean"] = (result["cohort_departed_holding_sum"] / c["cohort_departures"]
                                             if c["cohort_departures"] else None)
        return result


def observe_blocking(result, *, warmup=0.0, cohort_end=None, physical_neighbors=None):
    """Summarize saved events, failing on missing/corrupt/incompatible records.

    Rate/occupancy window: [warmup, H). Physical-admission cohort:
    [warmup, cohort_end), followed through H. ``cohort_restricted_mean`` is
    observed exposure per admitted slot, with survivors retained; it is not a
    Kaplan-Meier estimate or an unconditional holding-time mean when censored.
    Local blocking exposures can overlap and differ from global rejection:
    another endpoint may reject an arrival despite local free space.
    Supplying ordered physical_neighbors adds a pre-arrival histogram of the
    minimum uniform reserved-slot capacity that would admit each attempt in
    the observed state. The caller must include even zero-rate physical links.
    """
    _require(result.get("status") == "completed", "requires a completed simulation")
    _require(type(result.get("distillation_pairs")) is int and result["distillation_pairs"] == 1,
             "slot lineage currently requires D=1")
    _require(result.get("initial_pairs") == 0, "slot lineage requires zero initial inventory")
    horizon, ticks = result["horizon"], result["ticks_per_time_unit"]
    _require(type(ticks) is int and ticks > 0, "invalid ticks_per_time_unit")
    cohort_end = horizon if cohort_end is None else cohort_end
    _require(all(type(x) in (int, float) and math.isfinite(x) for x in (warmup, cohort_end, horizon))
             and 0 <= warmup < horizon and warmup <= cohort_end <= horizon, "invalid observation/cohort window")
    start, end, cohort = (round(x * ticks) for x in (warmup, horizon, cohort_end))
    _require(start < end and all(math.isclose(x * ticks, y, rel_tol=0, abs_tol=1e-6)
             for x, y in ((warmup, start), (horizon, end), (cohort_end, cohort))), "window must resolve to ticks")
    events = result.get("events")
    _require(isinstance(events, list) and events and events[-1].get("kind") == "finish"
             and events[-1].get("tick") == end, "missing complete event log")
    rows = result["occupancy_by_node"]
    nodes = [row["node"] for row in rows]
    _require(nodes and len(set(nodes)) == len(nodes), "invalid node inventory")
    limits = {row["node"]: row["memory_slots"] for row in rows}
    _require(all(v is None or (type(v) is int and v >= 0) for v in limits.values()), "invalid memory limits")
    quotas = {(row["node"], q["neighbor"]): q["slots"] for row in result["reservations"] for q in row["neighbors"]}
    _require(result["admission_policy"] in ("reserved", "tail_drop"), "unsupported admission policy")
    neighbor_ranks = {}
    required_capacities = Counter()
    if physical_neighbors is not None:
        _require(result["admission_policy"] == "reserved", "capacity-tail predictor requires reserved admission")
        _require(isinstance(physical_neighbors, Mapping) and set(physical_neighbors) == set(nodes),
                 "physical_neighbors must cover exactly the simulation nodes")
        order = {node: i for i, node in enumerate(nodes)}
        for node, neighbors in physical_neighbors.items():
            _require(isinstance(neighbors, (list, tuple)) and all(isinstance(n, Hashable) and n in order and n != node for n in neighbors)
                     and len(neighbors) == len(set(neighbors)), "invalid physical_neighbors adjacency")
            _require(list(neighbors) == sorted(neighbors, key=order.__getitem__),
                     "physical_neighbors must follow simulator node order")
            for rank, neighbor in enumerate(neighbors):
                neighbor_ranks[node, neighbor] = rank
            if limits[node] is not None:
                expected = {neighbor: limits[node] // len(neighbors) + (rank < limits[node] % len(neighbors))
                            for rank, neighbor in enumerate(neighbors)}
                _require({neighbor: quota for (owner, neighbor), quota in quotas.items() if owner == node} == expected,
                         "physical_neighbors disagree with recorded reservations")
        _require(all(node in physical_neighbors[neighbor] for node, neighbors in physical_neighbors.items()
                     for neighbor in neighbors), "physical_neighbors must be reciprocal")
    groups = {node: _Group({"node": node, "memory_slots": limits[node]}, limits[node], start, cohort, end, ticks)
              for node in nodes}
    origins = {}

    def origin_group(node, neighbor, tick):
        key = node, neighbor
        if key not in origins:
            capacity = quotas.get(key) if result["admission_policy"] == "reserved" else None
            origins[key] = _Group({"node": node, "neighbor": neighbor, "quota": capacity},
                                  capacity, start, cohort, end, ticks)
            origins[key].advance(tick)
        return origins[key]

    for node, neighbor in quotas:
        _require(node in groups and neighbor in groups and node != neighbor
                 and type(quotas[node, neighbor]) is int and quotas[node, neighbor] >= 0, "invalid reservation")
        origin_group(node, neighbor, 0)
    live, seen = {}, set()
    total, measured, reasons, total_reasons = Counter(), Counter(), Counter(), Counter()
    signature = hashlib.sha256()
    previous = 0

    def created_record(record, tick):
        identifier, endpoints = record["id"], record["endpoints"]
        _require(type(identifier) is int and identifier >= 0 and identifier not in seen, "duplicate/invalid pair identifier")
        _require(len(endpoints) == 2 and endpoints[0] != endpoints[1] and all(n in groups for n in endpoints),
                 "invalid created endpoints")
        _require(record["admitted_tick"] == tick, "incorrect pair episode admission time")
        seen.add(identifier)
        return identifier, endpoints

    def close_slot(node, slot, tick):
        neighbor, admitted = slot
        groups[node].depart(admitted, tick)
        origins[node, neighbor].depart(admitted, tick)

    for index, event in enumerate(events):
        tick, kind = event["tick"], event["kind"]
        _require(type(tick) is int and previous <= tick <= end, "invalid event ordering/tick")
        _require(kind in ("generate", "reject", "request", "swap", "complete", "expire", "finish"), "unsupported event kind")
        _require(tick < end or kind in ("expire", "finish"), "event outside observation horizon")
        _require(kind != "finish" or index == len(events) - 1, "premature finish event")
        for group in [*groups.values(), *origins.values()]:
            group.advance(tick)
        previous = tick
        within = start <= tick < end
        if kind in ("generate", "reject"):
            _require(not event.get("removed"), "generation cannot remove inventory")
            if kind == "generate":
                _require(len(event.get("created", [])) == 1, "generation must create one pair")
                record = event["created"][0]
                identifier, endpoints = created_record(record, tick)
                _require(not record["parents"], "physical generation cannot have parents")
            else:
                _require(not event.get("created"), "rejection cannot create inventory")
                endpoints = event["endpoints"]
                _require(len(endpoints) == 2 and endpoints[0] != endpoints[1] and all(n in groups for n in endpoints),
                         "invalid rejected endpoints")
            signature.update(json.dumps(["generate", tick, endpoints], separators=(",", ":")).encode())
            total["offered"] += 1
            total["accepted"] += kind == "generate"
            expected_reason = None
            required_capacity = 0
            for node, neighbor in (endpoints, endpoints[::-1]):
                _require(result["admission_policy"] != "reserved" or limits[node] is None
                         or (node, neighbor) in quotas, "missing physical-neighbor reservation")
                group = origin_group(node, neighbor, tick)
                if physical_neighbors is not None:
                    _require((node, neighbor) in neighbor_ranks, "observed generation missing from physical_neighbors")
                    required_capacity = max(required_capacity, groups[node].count + 1,
                                            len(physical_neighbors[node]) * group.count
                                            + neighbor_ranks[node, neighbor] + 1)
                full = limits[node] is not None and groups[node].count >= limits[node]
                reserved = group.capacity is not None and group.count >= group.capacity
                if expected_reason is None:
                    expected_reason = "hard_slots" if full else "neighbor_reservation" if reserved else None
                groups[node].attempt(tick, kind == "generate", full, reserved)
                group.attempt(tick, kind == "generate", full, reserved)
            _require((kind == "generate" and expected_reason is None) or
                     (kind == "reject" and event["reason"] == expected_reason and expected_reason is not None),
                     "admission decision disagrees with pre-event capacity")
            if kind == "reject":
                total_reasons[event["reason"]] += 1
            if within:
                measured["offered"] += 1
                measured["accepted"] += kind == "generate"
                if physical_neighbors is not None:
                    required_capacities[required_capacity] += 1
                if kind == "reject":
                    reasons[event["reason"]] += 1
            if kind == "generate":
                u, v = endpoints
                _require({r["node"]: r["neighbor"] for r in record["origins"]} == {u: v, v: u},
                         "incorrect generation origins")
                live[identifier] = {u: (v, tick), v: (u, tick)}
                for node, neighbor in (endpoints, endpoints[::-1]):
                    groups[node].admit(tick)
                    origins[node, neighbor].admit(tick)
        elif kind == "swap":
            removed, made, pivot = event["removed"], event["created"], event["pivot"]
            _require(len(removed) == len(set(removed)) == 2 and len(made) == 1
                     and all(i in live and pivot in live[i] for i in removed), "invalid D=1 swap lineage")
            identifier, endpoints = created_record(made[0], tick)
            _require(set(made[0]["parents"]) == set(removed) and len(made[0]["parents"]) == 2,
                     "incorrect swap parents")
            outer = {}
            for parent in removed:
                slots = live.pop(parent)
                close_slot(pivot, slots[pivot], tick)
                for node, slot in slots.items():
                    if node != pivot:
                        _require(node not in outer, "swap outer endpoints must differ")
                        outer[node] = slot
            _require(set(outer) == set(endpoints) and pivot not in outer, "incorrect swap output endpoints")
            _require({r["node"]: r["neighbor"] for r in made[0]["origins"]}
                     == {node: slot[0] for node, slot in outer.items()}, "swap changed physical origin")
            live[identifier] = outer
            total["swaps"] += 1
        elif kind in ("complete", "expire"):
            removed = event["removed"]
            _require(not event.get("created") and removed and len(set(removed)) == len(removed)
                     and all(i in live for i in removed), "invalid removed pair")
            if kind == "complete":
                _require(len(removed) == 1 and set(event["endpoints"]) == set(live[removed[0]]), "invalid D=1 completion")
                total["completed_requests"] += 1
                if within:
                    measured["completed_requests"] += 1
            else:
                total["expired_pairs"] += len(removed)
            for identifier in removed:
                for node, slot in live.pop(identifier).items():
                    close_slot(node, slot, tick)
        elif kind == "request":
            _require(not event.get("created") and not event.get("removed"), "request changed inventory")
            signature.update(json.dumps(["request", tick, event["endpoints"]], separators=(",", ":")).encode())
            total["offered_requests"] += 1
            if within:
                measured["offered_requests"] += 1
        else:
            _require(not event.get("created") and not event.get("removed"), "finish changed inventory")
        observed = {row["node"]: row["slots"] for row in event["occupancy"]}
        _require(len(event["occupancy"]) == len(nodes) and observed == {n: g.count for n, g in groups.items()},
                 "logged occupancy disagrees with physical slots")
        _require(all(limits[n] is None or g.count <= limits[n] for n, g in groups.items()), "hard slot limit exceeded")

    for counter, stored in (("offered", "offered_generation"), ("accepted", "admitted_generation"),
                            ("completed_requests", "completed_requests"), ("offered_requests", "offered_requests"),
                            ("swaps", "swaps"), ("expired_pairs", "expired_pairs")):
        _require(total[counter] == result[stored], f"event total mismatch: {stored}")
    _require(total["offered"] - total["accepted"] == result["admission_rejections"], "rejection total mismatch")
    _require(total_reasons == Counter(result["rejections_by_reason"]), "rejection reason total mismatch")
    _require(len(live) == result["remaining_pairs"], "remaining inventory mismatch")
    node_survivors = {node: [] for node in nodes}
    origin_survivors = {key: [] for key in origins}
    for slots in live.values():
        for node, (neighbor, admitted) in slots.items():
            node_survivors[node].append(admitted)
            origin_survivors[node, neighbor].append(admitted)
    node_rows = [group.result(node_survivors[node]) for node, group in groups.items()]
    for row, stored in zip(node_rows, rows):
        _require(math.isclose(row["full_run_occupancy_integral"], stored["integral"], rel_tol=1e-10, abs_tol=1e-8),
                 "saved occupancy integral mismatch")
        _require(groups[row["node"]].count == stored["final"], "saved final occupancy mismatch")
    duration = horizon - warmup
    rejected = measured["offered"] - measured["accepted"]
    optional = {}
    if physical_neighbors is not None:
        _require(sum(required_capacities.values()) == measured["offered"], "capacity histogram attempt mismatch")
        optional["required_capacity_histogram"] = [{"capacity": c, "attempts": n}
                                                   for c, n in sorted(required_capacities.items())]
    return {"horizon": horizon, "warmup": warmup, "window_duration": duration, "cohort_end": cohort_end,
            "offered": measured["offered"], "accepted": measured["accepted"], "rejected": rejected,
            "blocking_probability": rejected / measured["offered"] if measured["offered"] else None,
            "rejections_by_reason": dict(reasons), "completed_requests": measured["completed_requests"],
            "offered_requests": measured["offered_requests"], "throughput": measured["completed_requests"] / duration,
            "exogenous_signature": signature.hexdigest(), "nodes": node_rows,
            "origins": [group.result(origin_survivors[key]) for key, group in origins.items()], **optional}

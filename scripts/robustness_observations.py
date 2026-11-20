"""Disjoint-window observations for the frozen finite-memory policy study."""

from collections import Counter
import math

try:
    from .memory_policy_analysis import observe_policy
    from .verify_implementation_results import require
except ImportError:
    from memory_policy_analysis import observe_policy
    from verify_implementation_results import require


def _single_partner_absorbing_stall(data, live, pending):
    """Sufficient no-expiry 0-1-2 chain trap; not a general deadlock detector.

    Every possible generation uses the full center. All live pairs share its
    only partner, so no pivot has two partners. Only 02 demand is declared,
    and no 02 pair exists to release slots by consumption.
    """
    limits = {r["node"]: r["memory_slots"] for r in data["occupancy_by_node"]}
    if (data["cutoff_time"] is not None or set(limits) != {0, 1, 2}
            or limits[1] is None or limits[1] <= 0 or not pending):
        return False
    neighbors = {r["node"]: {q["neighbor"] for q in r["neighbors"]}
                 for r in data["reservations"]}
    if neighbors != {0: {1}, 1: {0, 2}, 2: {1}}:
        return False
    endpoint_demand = frozenset((0, 2))
    if ({frozenset(r["endpoints"]) for r in data["service_by_pair"]} != {endpoint_demand}
            or any(pair != endpoint_demand for pair in pending.values())):
        return False
    pairs = Counter(frozenset(item["endpoints"]) for item in live.values())
    return (len(pairs) == 1 and next(iter(pairs)) in (frozenset((0, 1)), frozenset((1, 2)))
            and sum(pairs.values()) == limits[1]
            and all(item["deadline_tick"] is None for item in live.values()))


def observe_robustness(data, *, warmup=500.0, split=2000.0):
    """Audit the full log, then measure [warmup, split) and [split, horizon).

    Initial/final backlog and the stall classifier use state immediately before
    boundary-tick events. Windows from one trajectory are correlated. A flag
    for zero service is an observation, not proof of an absorbing state.
    """
    horizon, ticks = data["horizon"], data["ticks_per_time_unit"]
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (warmup, split, horizon))
            and 0 <= warmup < split < horizon, "invalid robustness windows")
    require(type(ticks) is int and ticks > 0, "invalid ticks_per_time_unit")
    boundaries = [round(v * ticks) for v in (warmup, split, horizon)]
    require(boundaries[0] < boundaries[1] < boundaries[2]
            and all(math.isclose(v * ticks, t, rel_tol=0, abs_tol=1e-6)
                    for v, t in zip((warmup, split, horizon), boundaries)), "windows must resolve to ticks")
    audited = observe_policy(data, warmup=warmup)
    rows = [{"window": name, "start": start, "end": end,
             "initial_backlog": None, "final_backlog": None,
             "offered_requests": 0, "completed_requests": 0,
             "offered_generation": 0, "admitted_generation": 0, "rejected_generation": 0,
             "swaps": 0, "pressure_relaxed_swaps": 0}
            for name, start, end in (("early", warmup, split), ("late", split, horizon))]
    intervals = list(zip(boundaries[:-1], boundaries[1:]))
    areas = [0.0, 0.0]
    live, pending = {}, {}
    previous = 0
    for event in data["events"]:
        tick, kind = event["tick"], event["kind"]
        for index, (row, (start, end)) in enumerate(zip(rows, intervals)):
            areas[index] += len(pending) * max(0, min(tick, end) - max(previous, start)) / ticks
            if row["initial_backlog"] is None and tick >= start:
                row["initial_backlog"] = len(pending)
            if row["final_backlog"] is None and tick >= end:
                row["final_backlog"] = len(pending)
                row["single_partner_absorbing_stall"] = _single_partner_absorbing_stall(data, live, pending)
            if start <= tick < end:
                if kind in ("generate", "reject"):
                    row["offered_generation"] += 1
                    row["admitted_generation" if kind == "generate" else "rejected_generation"] += 1
                elif kind == "request":
                    row["offered_requests"] += 1
                elif kind == "complete":
                    row["completed_requests"] += 1
                elif kind == "swap":
                    row["swaps"] += 1
                    row["pressure_relaxed_swaps"] += event.get("pressure_relaxed", False)
        for identifier in event.get("removed", []):
            del live[identifier]
        for item in event.get("created", []):
            live[item["id"]] = item
        if kind == "request":
            pending[event["request_id"]] = frozenset(event["endpoints"])
        elif kind == "complete":
            del pending[event["request_id"]]
        previous = tick
    for row, area in zip(rows, areas):
        require(row["initial_backlog"] is not None and row["final_backlog"] is not None,
                "missing window boundary state")
        require(row["final_backlog"] - row["initial_backlog"]
                == row["offered_requests"] - row["completed_requests"], "window backlog conservation mismatch")
        duration = row["end"] - row["start"]
        completed, offered = row["completed_requests"], row["offered_generation"]
        row.update(throughput=completed / duration,
                   blocking_probability=row["rejected_generation"] / offered if offered else None,
                   mean_backlog=area / duration,
                   backlog_growth_rate=(row["final_backlog"] - row["initial_backlog"]) / duration,
                   swaps_per_completion=row["swaps"] / completed if completed else None,
                   zero_service=completed == 0,
                   zero_service_with_demand=completed == 0
                   and (row["initial_backlog"] > 0 or row["offered_requests"] > 0))
    for metric in ("completed_requests", "offered_generation", "admitted_generation", "swaps", "pressure_relaxed_swaps"):
        require(sum(row[metric] for row in rows) == audited[metric], f"partitioned {metric} mismatch")
    require(sum(row["offered_requests"] for row in rows) == sum(r["offered_requests"] for r in audited["per_pair"]),
            "partitioned offered requests mismatch")
    require(rows[0]["final_backlog"] == rows[1]["initial_backlog"]
            and rows[-1]["final_backlog"] == audited["final_backlog"], "partitioned backlog mismatch")
    require(math.isclose(sum(areas), audited["mean_backlog"] * (horizon - warmup), rel_tol=1e-12, abs_tol=1e-9),
            "partitioned backlog integral mismatch")
    return {"input_signature": audited["input_signature"], "event_signature": audited["event_signature"],
            "windows": rows}

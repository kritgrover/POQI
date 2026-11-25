"""Matched finite-horizon experiment for the local origin guard on a diamond."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
from itertools import combinations, product
import json
import math
from pathlib import Path

if __package__:
    from . import qcast_concurrent as model, qcast_concurrent_audit as audit, qcast_pilot_audit as physics
else:
    import qcast_concurrent as model, qcast_concurrent_audit as audit, qcast_pilot_audit as physics


ROOT = Path(__file__).resolve().parents[1]
HORIZON, WARMUP = 400, 100
GROUPS = {"archived": list(range(7271, 7281)), "fresh": list(range(8271, 8281))}
CONDITIONS = ((2, .5), (4, .5), (4, 1.0))
EDGES = ((0, 1), (0, 2), (1, 3), (2, 3))
PAIRS = ((0, 3), (0, 1), (1, 2))
POLICIES = ("pressure_relaxed", "pressure_oriented")
METRICS = ("throughput", "mean_backlog", "final_backlog", "longest_gap", "gaps_at_least_10",
           "trailing_gap", "right_censored", "zero_service")
require = physics.require


def busy_gaps(requests, completions, warmup, horizon):
    """Durations with demand waiting and no departure, clipped to [warmup,H]."""
    events = defaultdict(lambda: [0, 0])
    for request in requests:
        events[request["arrival"]][0] += 1
    for completion in completions:
        events[completion["time"]][1] += 1
    pending, started, durations = 0, None, []
    for time, (arrived, departed) in sorted(events.items()):
        if started is not None and departed and time > warmup:
            durations.append(time - max(warmup, started))
        pending += arrived - departed
        require(pending >= 0, "negative backlog in gap measurement")
        if pending == 0:
            started = None
        elif departed or started is None:
            started = time
    trailing = 0. if started is None else horizon - max(warmup, started)
    # A service at H can start a new open interval of observed length zero.
    if started is not None:
        durations.append(trailing)
    return {"longest_gap": max(durations, default=0.), "gaps_at_least_10": sum(d >= 10 for d in durations),
            "trailing_gap": trailing, "right_censored": int(started is not None)}


def pivot_choice(live, pivot, memory, guarded):
    """Independent D=1 choice from concrete pair records, in the diamond model."""
    buffers = defaultdict(list)
    origins = Counter()
    for item in live.values():
        u, v = item["endpoints"]
        buffers[u, v].append(item)
        origins.update((o["node"], o["neighbor"]) for o in item["origins"])
    def age(item):
        return (math.inf if item["deadline_tick"] is None else item["deadline_tick"], item["admitted_tick"], item["id"])
    def direction(item):
        return next(o["neighbor"] for o in item["origins"] if o["node"] == pivot)
    def inputs(node):
        return sorted(buffers[tuple(sorted((pivot, node)))], key=age)
    at_pivot = sum(n for (u, _), n in origins.items() if u == pivot)
    candidates = []
    for x, y in combinations((n for n in range(4) if n != pivot), 2):
        left, right = inputs(x), inputs(y)
        out = len(buffers[x, y])
        margin = min(len(left), len(right)) - 1 - out
        if margin < 0:
            continue
        def pressured(l, r):
            return at_pivot >= memory or max(origins[pivot, direction(l)], origins[pivot, direction(r)]) >= memory // 2
        if margin == 0 and not pressured(left[0], right[0]):
            continue  # A previously ineligible partner pair stays ineligible.
        choices = product(left, right) if guarded else [(left[0], right[0])]
        for l, r in choices:
            dl, dr = direction(l), direction(r)
            if guarded and dl == dr:
                continue
            if margin == 0 and not pressured(l, r):
                continue
            candidates.append((out, x, y, l["id"], r["id"], margin == 0))
            break
    return min(candidates) if candidates else None


def service_disabled(live, memory, guarded):
    """No possible service, swap or trial before an expiry changes the state."""
    if any(tuple(z["endpoints"]) in PAIRS for z in live.values()):
        return False
    occupied, origins = physics.occupancy(live, 4)
    for u, v in EDGES:
        if (max(occupied[u], occupied[v]) < memory and
                max(origins[u, v], origins[v, u]) < memory // 2):
            return False
    return all(pivot_choice(live, n, memory, guarded) is None for n in range(4))


def replay_physics(data):
    """Reconstruct admission, swaps, actual parent IDs and surviving endpoint origins."""
    memory, cutoff = data["memory"], 10 if "Cutoff10" in data["arm"] else None
    guarded = data["arm"].endswith("pressure_oriented")
    channels = [(u, v, 2*i+j) for i, (u, v) in enumerate(EDGES) for j in (0, 1)]
    require(data["channels"] == [list(ch) for ch in channels] and data["D"] == data["q"] == 1, "physics")
    model.audit_trajectory(data)  # Checks opportunities, service by phase and full queue ledger.
    live, next_id, certified = {}, 0, None
    nonoriented, same_origin_swaps = 0, 0
    arrivals = [r["arrival"] for r in data["requests"]]
    served = 0
    blocked_slots = []
    def consume(ids):
        for rid in ids:
            pair = tuple(data["requests"][rid]["pair"])
            del live[physics.oldest(live, pair)]
    for slot in data["slots"]:
        start = slot["start"]
        consume(slot["start_completed"])
        served += len(slot["start_completed"])
        if start >= WARMUP:
            waiting = bisect_right(arrivals, start) > served
            blocked_slots.append(waiting and service_disabled(live, memory, guarded))
        occupied, origins = physics.occupancy(live, 4)
        require(slot["allocation"]["pre_occupancy"] == occupied, "starting occupancy")
        order = sorted(channels, key=lambda ch: physics.uniform(data["seed"], "diamond", "ordering", start, *ch))
        selected = []
        for u, v, lane in order:
            if max(occupied[u], occupied[v]) >= memory or max(origins[u, v], origins[v, u]) >= memory // 2:
                continue
            selected.append(lane)
            occupied[u] += 1
            occupied[v] += 1
            origins[u, v] += 1
            origins[v, u] += 1
        require(slot["selected"] == selected and occupied == slot["reserved_occupancy"], "admission mismatch")
        end = start + 1
        expired = [i for i, z in live.items() if z["deadline_tick"] == end]
        require(expired == slot["settled"]["expired_ids"] and len(expired) == slot["expired_pairs"], "expiry")
        for i in expired:
            del live[i]
        for lane in slot["successful"]:
            u, v, _ = channels[lane]
            live[next_id] = {"id": next_id, "endpoints": [u, v], "admitted_tick": end,
                             "deadline_tick": end + cutoff if cutoff else None, "parents": [],
                             "origins": [{"node": u, "neighbor": v}, {"node": v, "neighbor": u}]}
            next_id += 1
        actual = iter(slot["settled"]["swap_log"])
        while True:
            changed = False
            for pivot in range(4):
                choice = pivot_choice(live, pivot, memory, guarded)
                if choice is None:
                    continue
                _, x, y, l, r, relaxed = choice
                event = next(actual, None)
                require(event is not None and event["pivot"] == pivot and event["removed"] == [l, r] and
                        event.get("pressure_relaxed", False) == relaxed, "independent swap choice mismatch")
                left, right = live.pop(l), live.pop(r)
                def origin(z, node):
                    return next(o for o in z["origins"] if o["node"] == node)
                matching_origins = origin(left, pivot) == origin(right, pivot)
                same_origin_swaps += int(matching_origins)
                nonoriented += int(matching_origins and start >= WARMUP)
                live[next_id] = {"id": next_id, "endpoints": [x, y], "admitted_tick": end,
                                 "deadline_tick": min(left["deadline_tick"], right["deadline_tick"]) if cutoff else None,
                                 "parents": [l, r], "origins": [origin(left, x), origin(right, y)]}
                require(event["created"] == [live[next_id]], "swap output or origin mismatch")
                next_id += 1
                changed = True
            if not changed:
                break
        require(next(actual, None) is None and list(live.values()) == slot["settled"]["live_pairs"], "settling")
        consume(slot["end_completed"])
        served += len(slot["end_completed"])
        require(list(live.values()) == slot["final_inventory"] and slot["discarded_pairs"] == 0, "final inventory")
        if certified is not None:
            require(not selected and not slot["swaps"] and not slot["start_completed"] and
                    not slot["end_completed"], "certified state changed")
        elif cutoff is None and service_disabled(live, memory, guarded):
            certified = end
    return {"first_certified_tick": certified, "same_origin_swaps_full": same_origin_swaps,
            "same_origin_swaps_measured": nonoriented, "blocked_pending_slots": sum(blocked_slots)}


def measurements(data):
    audits = replay_physics(data)
    observed = audit.observation(data, WARMUP)
    metrics = {}
    for pair in (None, *PAIRS):
        requests = [r for r in data["requests"] if pair is None or tuple(r["pair"]) == pair]
        ids = {r["id"] for r in requests}
        departures = [c for c in data["completions"] if c["id"] in ids]
        base = observed if pair is None else next(z for z in observed["per_pair"] if tuple(z["pair"]) == pair)
        scope = "all" if pair is None else "".join(map(str, pair))
        metrics[scope] = {k: base[k] for k in ("throughput", "mean_backlog", "final_backlog")}
        metrics[scope].update(zero_service=int(base["completed"] == 0),
                             **busy_gaps(requests, departures, WARMUP, data["horizon"]))
    metrics["all"]["blocked_pending_slots"] = audits["blocked_pending_slots"]
    return {"metrics": metrics, **audits, "swaps": observed["swaps"], "attempts": observed["attempts"],
            "expired": observed["expired_pairs"]}


def trajectory_bytes(data):
    return json.dumps(data, separators=(",", ":"), allow_nan=False).encode()


def filename(memory, p, cutoff, seed, policy):
    return f"m{memory}-p{p:g}-cut{cutoff or 'none'}-s{seed}-{policy}.json.gz"


def run_pair(job):
    directory, archive, reference, group, memory, p, cutoff, seed, verify = job
    prefix = "POQI-Cutoff10" if cutoff else "POQI-Persistent"
    rows, dynamics = [], []
    for policy in POLICIES:
        arm = f"{prefix}-{policy}"
        path = directory / "runs" / filename(memory, p, cutoff, seed, policy)
        if verify:
            compressed = path.read_bytes()
            data = json.loads(gzip.decompress(compressed))
        else:
            data = model.run_trajectory("diamond", memory, p, seed, arm, HORIZON, None)
            compressed = gzip.compress(trajectory_bytes(data), compresslevel=5, mtime=0)
            with path.open("xb") as stream:
                stream.write(compressed)
        require((data["memory"], data["p"], data["seed"], data["arm"], data["horizon"], data["service_mode"]) ==
                (memory, p, seed, arm, HORIZON, "concurrent_per_pair"), "wrong trajectory")
        if policy == POLICIES[0] and reference is not None:
            source = (archive / reference["artifact"]).read_bytes()
            require(hashlib.sha256(source).hexdigest() == reference["sha256"], "archive hash mismatch")
            require(data == json.loads(gzip.decompress(source)), "baseline differs from archived trajectory")
        dynamics.append(hashlib.sha256(trajectory_bytes({k: v for k, v in data.items() if k != "arm"})).hexdigest())
        rows.append({"group": group, "memory": memory, "p": p, "cutoff": cutoff, "seed": seed, "policy": policy,
                     "raw": path.name, "sha256": hashlib.sha256(compressed).hexdigest(),
                     "requests_sha256": data["workload_sha256"], "potentials_sha256": data["potential_sha256"],
                     "archived_baseline_sha256": reference["sha256"] if reference and policy == POLICIES[0] else None,
                     **measurements(data)})
    require(all(rows[0][key] == rows[1][key] for key in ("requests_sha256", "potentials_sha256")), "unmatched inputs")
    identical = dynamics[0] == dynamics[1]
    require(memory != 2 or identical, "two-slot orientation invariant failed")
    for row in rows:
        row["identical_dynamics"] = identical
    return rows


def summarize(records):
    indexed = defaultdict(dict)
    for row in records:
        key = (row["group"], row["memory"], row["p"], row["cutoff"])
        idx = row["seed"], row["policy"]
        require(idx not in indexed[key], "duplicate trajectory")
        indexed[key][idx] = row
    report = []
    for (group, memory, p, cutoff), cell in indexed.items():
        require(set(cell) == set(product(GROUPS[group], POLICIES)), "incomplete seed pair")
        for scope in ("all", "03", "01", "12"):
            item = {"group": group, "memory": memory, "p": p, "cutoff": cutoff, "scope": scope}
            for metric in ((*METRICS, "blocked_pending_slots") if scope == "all" else METRICS):
                a, b = [[cell[s, pol]["metrics"][scope][metric] for s in GROUPS[group]] for pol in POLICIES]
                item[metric] = {"plain": model.pilot.interval(a), "guarded": model.pilot.interval(b),
                                "paired_change": model.pilot.interval([y - x for x, y in zip(a, b)])}
            report.append(item)
    return report


def experiment(directory, archive, workers, verify=False):
    require(workers >= 1, "workers must be positive")
    mbytes = (archive / "manifest.json").read_bytes()
    manifest = json.loads(mbytes)
    require(manifest["status"] == "passed" and manifest["horizon"] == HORIZON and manifest["warmup"] == WARMUP
            and manifest["seeds"] == GROUPS["archived"], "incorrect archive protocol")
    refs = {(r["memory"], r["p"], r["arm"], r["seed"]): r for r in manifest["runs"]
            if r["topology"] == "diamond" and r["service_mode"] == "concurrent_per_pair"}
    if not verify:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "runs").mkdir()
    jobs = []
    for group, seeds in GROUPS.items():
        for (m, p), cut, seed in product(CONDITIONS, (None, 10), seeds):
            key = (m, p, "POQI-Cutoff10-pressure_relaxed" if cut else "POQI-Persistent-pressure_relaxed", seed)
            ref = refs[key] if group == "archived" else None
            jobs.append((directory, archive, ref, group, m, p, cut, seed, verify))
    if workers == 1:
        records = [r for job in jobs for r in run_pair(job)]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            records = [r for pair in pool.map(run_pair, jobs) for r in pair]
    sources = [Path(__file__).resolve(), Path(model.__file__), Path(model.pilot.__file__), Path(audit.__file__),
               Path(physics.__file__), ROOT / "scripts/qcast_poqi.py", ROOT / "src/poqi/simulation/inventory.py",
               ROOT / "src/poqi/simulation/sequence_adapter.py"]
    outputs = {"observations.json": records, "summary.json": summarize(records), "manifest.json": {
        "archive_manifest_sha256": hashlib.sha256(mbytes).hexdigest(), "groups": GROUPS,
        "conditions": [list(c) for c in CONDITIONS], "cutoffs": [None, 10], "policies": list(POLICIES),
        "horizon": HORIZON, "warmup": WARMUP, "trajectory_count": len(records),
        "source_hashes": {s.relative_to(ROOT).as_posix(): physics.digest(s) for s in sources}}}
    for name, value in outputs.items():
        dest = directory / name
        if verify:
            require(json.loads(dest.read_bytes()) == value, f"saved {name} disagrees with recomputation")
        else:
            with dest.open("x", encoding="utf-8") as f:
                json.dump(value, f, indent=2, allow_nan=False)
                f.write("\n")
    print(f"{len(records)} trajectories validated, {sum(r['archived_baseline_sha256'] is not None for r in records)} archive matches")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, default=ROOT / "results/qcast/concurrent-main-01")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--verify", action="store_true", help="recheck saved trajectories and reports read-only")
    arguments = parser.parse_args()
    experiment(arguments.output, arguments.archive, arguments.workers, arguments.verify)

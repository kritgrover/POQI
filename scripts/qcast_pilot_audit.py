"""Independent raw-artifact replay for the matched Q-CAST pilot.

Does not import the pilot runner, arm implementation, observer or summarizer.
Rebuilds workload/opportunity streams, physical state, service and statistics.
"""

import argparse
from collections import Counter, defaultdict, deque
import gzip
import hashlib
import json
import math
from pathlib import Path
import random

from scipy.stats import t


ROOT = Path(__file__).resolve().parents[1]
REVISION = "0a0251dd5f38eb1669ff6abe18ab83436ddbba18"
ARMS = ("QCAST-Slot-FIFO", "POQI-Slot-balancing", "POQI-Slot-pressure_relaxed",
        "POQI-Persistent-balancing", "POQI-Persistent-pressure_relaxed",
        "POQI-Cutoff10-balancing", "POQI-Cutoff10-pressure_relaxed")
SPECS = {
    "chain": (3, [(0, 1), (1, 2)], {(0, 2): .75}),
    "diamond": (4, [(0, 1), (0, 2), (1, 3), (2, 3)], {(0, 3): .5, (0, 1): .25, (1, 2): .15}),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, context="value"):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), f"{context}: fields differ")
        for key in expected:
            close(actual[key], expected[key], f"{context}.{key}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), f"{context}: length differs")
        for i, (a, b) in enumerate(zip(actual, expected)):
            close(a, b, f"{context}[{i}]")
    elif isinstance(expected, float):
        require(isinstance(actual, (int, float)) and math.isfinite(actual)
                and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10), f"{context}: numeric mismatch")
    else:
        require(actual == expected, f"{context}: {actual!r} != {expected!r}")


def uniform(seed, name, namespace, *parts):
    key = json.dumps([seed, name, namespace, *parts], separators=(",", ":")).encode()
    number = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 11
    return number / 2**53


def reconstruct_requests(name, seed, horizon):
    rows = []
    for pair, rate in SPECS[name][2].items():
        key = json.dumps([seed, name, "requests", *pair]).encode()
        generator = random.Random(int.from_bytes(hashlib.sha256(key).digest(), "big"))
        now = 0.0
        while True:
            now += -math.log(1.0-generator.random()) / rate
            if now >= horizon:
                break
            rows.append({"pair": list(pair), "arrival": now})
    rows.sort(key=lambda r: (r["arrival"], r["pair"]))
    return [{"id": i, **row} for i, row in enumerate(rows)]


def state_counts(live):
    return Counter(tuple(row["endpoints"]) for row in live.values())


def oldest(live, pair):
    choices = [r for r in live.values() if tuple(r["endpoints"]) == pair]
    return min(choices, key=lambda r: (math.inf if r["deadline_tick"] is None else r["deadline_tick"],
                                      r["admitted_tick"], r["id"]))["id"] if choices else None


def occupancy(live, n):
    total = [0] * n
    origins = Counter()
    for pair in live.values():
        for node in pair["endpoints"]:
            total[node] += 1
        for origin in pair["origins"]:
            origins[origin["node"], origin["neighbor"]] += 1
    return total, origins


def serve(pending, counts, ids, tick, requests, completions, live=None):
    consumed = []
    while pending and counts[tuple(requests[pending[0]]["pair"])] > 0:
        request = pending.popleft()
        pair = tuple(requests[request]["pair"])
        counts[pair] -= 1
        if live is not None:
            identifier = oldest(live, pair)
            require(identifier is not None, "service lacks physical pair")
            del live[identifier]
        completions.append({"id": request, "time": tick})
        consumed.append(request)
    require(consumed == ids, "FIFO completions disagree with physical available pairs")


def replay_poqi_slot(data, row, live, pending, requests, completions, order, quotas, seen_ids):
    n, edges, _ = SPECS[data["topology"]]
    start, memory = row["start"], data["memory"]
    persistent = not data["arm"].startswith("POQI-Slot")
    cutoff = 10 if data["arm"].startswith("POQI-Cutoff10") else None
    if persistent:
        serve(pending, state_counts(live), row["start_completed"], start, requests, completions, live)
    else:
        require(not row["start_completed"] and not live, "reset arm retained inventory or served at start")
    require(all(r["deadline_tick"] is None or r["deadline_tick"] > start for r in live.values()),
            "due pair survived preceding boundary")
    occupied, origins = occupancy(live, n)
    close(row["allocation"]["pre_occupancy"], occupied, "pre-occupancy")
    require(row["allocation"]["pre_live_pairs"] == len(live), "pre-live pair count")
    require(row["storage_qubit_time"] == 2*len(live), "stored qubit-time")
    selected, blocked = [], []
    for u, v, channel in order:
        reason = None
        for node, neighbor in ((u, v), (v, u)):
            if occupied[node] >= memory:
                reason = "hard_slots"
                break
            if origins[node, neighbor] >= quotas[node, neighbor]:
                reason = "neighbor_reservation"
                break
        if reason:
            blocked.append({"channel": channel, "reason": reason})
        else:
            selected.append(channel)
            occupied[u] += 1
            occupied[v] += 1
            origins[u, v] += 1
            origins[v, u] += 1
    require(selected == row["selected"] and blocked == row["blocked"], "pre-outcome attempt admission")
    close(row["reserved_occupancy"], occupied, "reserved occupancy")
    end = start + 1
    expired = [i for i, r in live.items() if r["deadline_tick"] is not None and r["deadline_tick"] <= end]
    require(expired == row["settled"]["expired_ids"] and len(expired) == row["expired_pairs"], "expiry replay")
    require(row["allocation"]["expired_at_start"] == 0, "unexpected start expiry")
    for identifier in expired:
        del live[identifier]
    generated = row["settled"]["generated"]
    require([g["channel"] for g in generated] == row["successful"], "generation order mismatch")
    channels = data["channels"]
    for generated_row in generated:
        pair = generated_row["pair"]
        u, v, _ = channels[generated_row["channel"]]
        require(pair["id"] not in seen_ids, "reused physical pair identifier")
        seen_ids.add(pair["id"])
        expected = {"id": pair["id"], "endpoints": [u, v], "admitted_tick": end,
                    "deadline_tick": None if cutoff is None else end+cutoff, "parents": [],
                    "origins": [{"node": u, "neighbor": v}, {"node": v, "neighbor": u}]}
        close(pair, expected, "elementary pair")
        live[pair["id"]] = pair
    logs = row["settled"]["swap_log"]
    log_position = 0
    relaxed_count = 0
    pressure = data["arm"].endswith("pressure_relaxed")
    while True:
        changed = False
        for pivot in range(n):
            counts = state_counts(live)
            occ, origin = occupancy(live, n)
            candidates = []
            for x in range(n):
                for y in range(x+1, n):
                    if pivot in (x, y):
                        continue
                    left, right, output = tuple(sorted((pivot, x))), tuple(sorted((pivot, y))), (x, y)
                    l, r, o = counts[left], counts[right], counts[output]
                    if l == 0 or r == 0:
                        continue
                    ids = [oldest(live, left), oldest(live, right)]
                    preferred = o+1 <= min(l-1, r-1)
                    full_origin = any(origin[pivot, next(a["neighbor"] for a in live[i]["origins"]
                                                        if a["node"] == pivot)] >=
                                      quotas[pivot, next(a["neighbor"] for a in live[i]["origins"]
                                                         if a["node"] == pivot)] > 0 for i in ids)
                    relaxed = pressure and not preferred and o <= min(l-1, r-1) and (occ[pivot] == memory or full_origin)
                    if preferred or relaxed:
                        candidates.append((o, x, y, ids, bool(relaxed)))
            if not candidates:
                continue
            _, x, y, ids, relaxed = min(candidates)
            require(log_position < len(logs), "eligible frozen-rule swap omitted")
            event = logs[log_position]
            log_position += 1
            require(event["kind"] == "swap" and event["pivot"] == pivot and event["tick"] == end,
                    "frozen-rule swap order changed")
            require(event["removed"] == ids and bool(event.get("pressure_relaxed", False)) == relaxed,
                    "swap consumed wrong inputs or predicate")
            parents = [live[i] for i in ids]
            output = event["created"][0]
            require(len(event["created"]) == 1 and output["id"] not in seen_ids, "swap output identity")
            seen_ids.add(output["id"])
            deadlines = [r["deadline_tick"] for r in parents if r["deadline_tick"] is not None]
            out_origins = [{"node": x, "neighbor": next(o["neighbor"] for o in parents[0]["origins"] if o["node"] == x)},
                           {"node": y, "neighbor": next(o["neighbor"] for o in parents[1]["origins"] if o["node"] == y)}]
            close(output, {"id": output["id"], "endpoints": [x, y], "admitted_tick": end,
                           "deadline_tick": min(deadlines) if deadlines else None,
                           "parents": ids, "origins": out_origins}, "inherited swap output")
            for identifier in ids:
                del live[identifier]
            live[output["id"]] = output
            relaxed_count += relaxed
            changed = True
        if not changed:
            break
    require(log_position == len(logs) == row["swaps"], "extra swaps or swap totals")
    require(relaxed_count == row["settled"]["pressure_relaxed_swaps"], "relaxation total")
    close({r["id"]: r for r in row["settled"]["live_pairs"]}, live, "settled inventory")
    serve(pending, state_counts(live), row["end_completed"], end, requests, completions, live)
    if persistent:
        require(row["discarded_pairs"] == 0, "persistent arm reset")
    else:
        require(row["discarded_pairs"] == len(live), "reset discard count")
        live.clear()
    close({r["id"]: r for r in row["final_inventory"]}, live, "final inventory")
    return live


def replay_native_slot(data, row, pending, requests, completions):
    require(not row["start_completed"], "native slot served before generation")
    channels, response = data["channels"], row["native"]
    n = SPECS[data["topology"]][0]
    selected, successes = set(row["selected"]), set(row["successful"])
    require(row["selected"] == response["assigned"] and row["successful"] == response["successful"], "native channel records")
    occ = [sum(i in selected and v in edge[:2] for i, edge in enumerate(channels)) for v in range(n)]
    require(occ == row["reserved_occupancy"] == response["occupancy"], "native occupancy")
    claims = Counter()
    for allocation in response["major_paths"] + [r["path"] for r in response["recovery_paths"]]:
        path, width = allocation["nodes"], allocation["width"]
        require(len(path) == len(set(path)) and width > 0, "native nonsimple allocation")
        for u, v in zip(path, path[1:]):
            claims[tuple(sorted((u, v)))] += width
    expected_claims = Counter(tuple(channels[i][:2]) for i in selected)
    require(claims == expected_claims, "native path/channel exclusive claims")
    # Each vertex is one physical channel endpoint qubit. Physical links and
    # successful Bell measurements form disjoint chains; free ends are ebits.
    adjacency = defaultdict(list)
    for channel in successes:
        u, v, _ = channels[channel]
        adjacency[u, channel].append((v, channel))
        adjacency[v, channel].append((u, channel))
    swapped = set()
    for connection in response["successful_swap_inputs"]:
        pivot, inputs = connection["node"], connection["channels"]
        require(len(inputs) == 2 and inputs[0] != inputs[1], "invalid native BSM")
        ends = [(pivot, channel) for channel in inputs]
        require(all(end in adjacency and end not in swapped for end in ends), "reused or missing native swap input")
        swapped.update(ends)
        adjacency[ends[0]].append(ends[1])
        adjacency[ends[1]].append(ends[0])
    require(len(swapped)//2 == row["swaps"] == response["swaps"], "native swap total")
    for flags in response["post_p4_channels"]:
        channel = flags["channel"]
        u, v, _ = channels[channel]
        require(bool(flags["s1"]) == ((u, channel) in swapped)
                and bool(flags["s2"]) == ((v, channel) in swapped), "native swap flags")
    paths = defaultdict(list)
    visited = set()
    for vertex in adjacency:
        if vertex in visited:
            continue
        component, stack = set(), [vertex]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current])
        visited.update(component)
        endpoints = sorted(v for v in component if len(adjacency[v]) == 1)
        require(len(endpoints) == 2 and endpoints[0][0] != endpoints[1][0], "nonphysical final ebit component")
        current, previous, sequence = endpoints[0], None, []
        while current != endpoints[1]:
            choices = [v for v in adjacency[current] if v != previous]
            require(len(choices) == 1, "branched native ebit")
            following = choices[0]
            if following[0] != current[0]:
                sequence.append(current[1])
            previous, current = current, following
        paths[endpoints[0][0], endpoints[1][0]].append(sequence)
    for physical in response["all_pairs"]:
        expected = paths[tuple(physical["pair"])]
        require(physical["count"] == len(expected) and sorted(physical["paths"]) == sorted(expected), "native physical pair traversal")
    active = sorted({tuple(requests[i]["pair"]) for i in pending})
    require([tuple(r["pair"]) for r in response["delivered"]] == active, "native demand visibility")
    for result in response["delivered"]:
        expected = paths[tuple(result["pair"])]
        require(result["count"] == len(expected) and sorted(result["paths"]) == sorted(expected), "native endpoint-valid delivery")
    require(response["author_accounting_discrepancy"] == any(r["count"] != r["author_count"] for r in response["delivered"]),
            "author accounting discrepancy flag")
    total = sum(map(len, paths.values()))
    require(total == response["total_remaining_pairs"] == len(successes)-row["swaps"], "native physical conservation")
    serve(pending, Counter({pair: len(paths[pair]) for pair in active}), row["end_completed"],
          row["start"]+1, requests, completions)
    require(row["discarded_pairs"] == total-len(row["end_completed"]) and row["remaining_pairs"] == 0,
            "native reset/service accounting")
    require(response["reset_clean"] and row["expired_pairs"] == 0 and row["storage_qubit_time"] == 0,
            "native reset contract")


def replay(data):
    name, seed, horizon = data["topology"], data["seed"], data["horizon"]
    n, edges, _ = SPECS[name]
    require(data["q"] == data["D"] == 1 and data["p"] in (1, .5), "unexpected physical pilot model")
    channels = [[u, v, 2*i+lane] for i, (u, v) in enumerate(edges) for lane in range(2)]
    require(channels == data["channels"], "channel opportunity budget changed")
    requests = reconstruct_requests(name, seed, horizon)
    close(data["requests"], requests, "request trace")
    require(data["workload_sha256"] == hashlib.sha256(json.dumps(data["requests"], sort_keys=True).encode()).hexdigest(), "request digest")
    quotas = {}
    for node in range(n):
        neighbors = sorted(v if u == node else u for u, v in edges if node in (u, v))
        base, remainder = divmod(data["memory"], len(neighbors))
        quotas.update({(node, neighbor): base+(i < remainder) for i, neighbor in enumerate(neighbors)})
    pending, completions, live, seen_ids = deque(), [], {}, set()
    cursor = 0
    ledger = hashlib.sha256()
    stock = 0
    require(len(data["slots"]) == horizon, "missing slot")
    for start, row in enumerate(data["slots"]):
        require(row["start"] == start, "slot order")
        while cursor < len(requests) and requests[cursor]["arrival"] <= start:
            pending.append(cursor)
            cursor += 1
        potentials = [uniform(seed, name, "link", start, u, v, i % 2) for u, v, i in channels]
        ledger.update(json.dumps(potentials, separators=(",", ":")).encode())
        require(len(row["selected"]) == len(set(row["selected"])), "opportunity reuse")
        require(all(0 <= i < len(channels) for i in row["selected"]), "unknown opportunity")
        require(row["successful"] == [i for i in row["selected"] if potentials[i] < data["p"]], "uncoupled link outcomes")
        if data["arm"] == ARMS[0]:
            replay_native_slot(data, row, pending, requests, completions)
        else:
            order = sorted(channels, key=lambda c: uniform(seed, name, "ordering", start, *c))
            live = replay_poqi_slot(data, row, live, pending, requests, completions, order, quotas, seen_ids)
        require(row["qubit_time"] == sum(row["reserved_occupancy"]) == row["storage_qubit_time"]+2*len(row["selected"]),
                "allocated memory-time conservation")
        require(all(0 <= v <= data["memory"] for v in row["reserved_occupancy"]), "physical memory capacity")
        stock += len(row["successful"])-row["swaps"]-row["expired_pairs"]-row["discarded_pairs"]
        stock -= len(row["start_completed"])+len(row["end_completed"])
        require(stock >= 0 and stock == row["remaining_pairs"], "pair conservation")
    pending.extend(range(cursor, len(requests)))
    require(list(pending) == data["pending"] and completions == data["completions"], "request service/backlog replay")
    require(data["potential_sha256"] == ledger.hexdigest(), "potential ledger digest")
    return len(completions)


def observation(data, warmup):
    horizon = data["horizon"]
    duration = horizon-warmup
    departures = {r["id"]: r["time"] for r in data["completions"]}
    requests = data["requests"]
    # Integrate the actual queue by chronological events, independently of the
    # runner's per-request overlap formula. Hidden-but-arrived demand counts.
    events = [(r["arrival"], 1) for r in requests] + [(r["time"], -1) for r in data["completions"]]
    events.sort()
    previous, backlog, full_area, area = 0, 0, 0.0, 0.0
    for when, delta in events + [(horizon, 0)]:
        full_area += backlog*(when-previous)
        area += backlog*max(0, when-max(previous, warmup))
        backlog += delta
        require(backlog >= 0, "negative chronological backlog")
        previous = when
    waits = [departures.get(r["id"], horizon)-r["arrival"] for r in requests]
    close(full_area, math.fsum(waits), "censored waiting area")
    selected_requests = [r for r in requests if warmup < departures.get(r["id"], -1) <= horizon]
    latency = [departures[r["id"]]-r["arrival"] for r in selected_requests]
    pending = [r for r in requests if r["id"] not in departures]
    qstart = sum(r["arrival"] <= warmup for r in requests)-sum(c["time"] <= warmup for c in data["completions"])
    rows = [r for r in data["slots"] if r["start"] >= warmup]
    attempts, swaps, done = sum(len(r["selected"]) for r in rows), sum(r["swaps"] for r in rows), len(selected_requests)
    last = data["slots"][-1].get("final_inventory", [])
    absorbing = (data["topology"] == "chain" and data["arm"].startswith("POQI-Persistent") and bool(pending)
                 and len(last) == data["memory"] and {tuple(p["endpoints"]) for p in last} in ({(0, 1)}, {(1, 2)}))
    avg = lambda values: math.fsum(values)/len(values) if values else None
    return {
        "topology": data["topology"], "memory": data["memory"], "p": data["p"], "seed": data["seed"], "arm": data["arm"],
        "completed": done, "throughput": done/duration, "mean_backlog": area/duration, "initial_backlog": qstart,
        "final_backlog": len(pending), "backlog_growth": (len(pending)-qstart)/duration,
        "completed_mean_latency": avg(latency), "unfinished_mean_age": avg([horizon-r["arrival"] for r in pending]),
        "restricted_mean_wait_full_horizon": avg(waits), "attempts": attempts,
        "attempts_per_completion": attempts/done if done else None, "swaps": swaps,
        "swaps_per_completion": swaps/done if done else None,
        "allocated_qubits_mean": sum(r["qubit_time"] for r in rows)/duration,
        "stored_qubits_mean": sum(r["storage_qubit_time"] for r in rows)/duration,
        "failed_attempts": sum(len(r["selected"])-len(r["successful"]) for r in rows),
        "skipped_opportunities": len(data["channels"])*duration-attempts,
        "expired_pairs": sum(r["expired_pairs"] for r in rows), "discarded_pairs": sum(r["discarded_pairs"] for r in rows),
        "zero_service": done == 0, "absorbing_stall": absorbing,
        "native_accounting_discrepancy_slots": sum(bool(r.get("native", {}).get("author_accounting_discrepancy")) for r in rows),
        "per_pair": [{"pair": list(pair), "completed": sum(tuple(r["pair"]) == pair for r in selected_requests),
                      "pending": sum(tuple(r["pair"]) == pair for r in pending),
                      "offered_total": sum(tuple(r["pair"]) == pair for r in requests)} for pair in SPECS[data["topology"]][2]],
        "workload_sha256": data["workload_sha256"], "potential_sha256": data["potential_sha256"],
    }


def ci(values):
    valid = [v for v in values if v is not None]
    mean = math.fsum(valid)/len(valid) if valid else None
    half = None
    if len(valid) > 1:
        variance = math.fsum((x-mean)**2 for x in valid)/(len(valid)-1)
        half = float(t.ppf(.975, len(valid)-1))*math.sqrt(variance/len(valid))
    return {"mean": mean, "low": mean-half if half is not None else None,
            "high": mean+half if half is not None else None, "n": len(valid), "undefined": len(values)-len(valid)}


def audit(directory, historical=False):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/"manifest.json").read_text())
    require(manifest["status"] == "passed" and manifest["author_revision"] == REVISION, "incomplete or wrong-source pilot")
    current_matches = {name: digest(ROOT/name) == value for name, value in manifest["source_hashes"].items()}
    if not historical:
        require(all(current_matches.values()), "source files changed since pilot; do not claim current-source validation")
    build = Path(manifest["build"])
    built = json.loads((build.parent/"build-manifest.json").read_text())
    require(built["revision"] == REVISION, "native build revision")
    for name, checksum in built["source_hashes"].items():
        require(digest(build/name) == checksum, f"modified staged author source: {name}")
    require(digest(build/"src/main/kotlin/poqi/qcast/SlotBridge.kt") == built["bridge_sha256"], "staged native bridge changed")
    for path, checksum in built["dependency_hashes"].items():
        require(digest(path) == checksum, f"native dependency changed: {path}")
    observations, run_keys, hashes = [], set(), defaultdict(set)
    slot_count = completed_count = 0
    for entry in manifest["runs"]:
        path = directory/entry["artifact"]
        require(digest(path) == entry["sha256"], f"artifact changed: {path}")
        data = json.loads(gzip.decompress(path.read_bytes()))
        require(data["horizon"] == manifest["horizon"], "horizon mismatch")
        key = data["topology"], data["memory"], data["p"], data["seed"], data["arm"]
        require(key not in run_keys, "duplicate trajectory")
        run_keys.add(key)
        completed_count += replay(data)
        slot_count += len(data["slots"])
        observations.append(observation(data, manifest["warmup"]))
        hashes[data["topology"], data["seed"]].add((data["workload_sha256"], data["potential_sha256"]))
    expected_keys = {(name, memory, p, seed, arm) for name, capacities in (("chain", (2, 3, 4)), ("diamond", (2, 4)))
                     for memory in capacities for p in (1., .5) for seed in manifest["seeds"] for arm in ARMS}
    require(run_keys == expected_keys, "missing/extra pilot trajectories")
    require(all(len(values) == 1 for values in hashes.values()), "cross-policy/capacity/potential traces differ")
    saved = json.loads((directory/"observations.json").read_text())
    close(saved, observations, "observations")
    report = json.loads((directory/"report.json").read_text())
    grouped = defaultdict(list)
    for row in observations:
        grouped[row["topology"], row["memory"], row["p"], row["arm"]].append(row)
    require(len(report["summaries"]) == len(grouped), "missing report groups")
    for group in report["summaries"]:
        key = group["topology"], group["memory"], group["p"], group["arm"]
        rows = grouped[key]
        for metric, value in group.items():
            if isinstance(value, dict):
                close(value, ci([r[metric] for r in rows]), f"summary {key}/{metric}")
        require(group["zero_service_runs"] == sum(r["zero_service"] for r in rows), "zero-service summary")
        require(group["absorbing_runs"] == sum(r["absorbing_stall"] for r in rows), "absorbing summary")
        require(group["native_accounting_discrepancy_slots"] == sum(r["native_accounting_discrepancy_slots"] for r in rows), "native discrepancy summary")
    expected_pairs = {(name, memory, p, left, right) for name, memory, p, _ in grouped
                      for left, right in [(ARMS[0], arm) for arm in ARMS[1:]] + [(ARMS[2], ARMS[1]), (ARMS[4], ARMS[3]), (ARMS[6], ARMS[5])]}
    require(len(report["paired_contrasts"]) == len(expected_pairs), "paired contrast count")
    observed_pairs = set()
    for contrast in report["paired_contrasts"]:
        key = contrast["topology"], contrast["memory"], contrast["p"]
        observed_pairs.add((*key, contrast["left"], contrast["right"]))
        sides = [{r["seed"]: r for r in grouped[*key, arm]} for arm in (contrast["left"], contrast["right"])]
        require(sides[0].keys() == sides[1].keys() == set(manifest["seeds"]), "unpaired replicates")
        for metric, value in contrast.items():
            if isinstance(value, dict):
                close(value, ci([sides[0][s][metric]-sides[1][s][metric] for s in manifest["seeds"]]), "paired interval")
    require(observed_pairs == expected_pairs, "paired contrast identities")
    result = {"status": "passed", "audit_sha256": digest(__file__), "trajectories": len(observations),
              "slots_replayed": slot_count, "completed_requests_replayed": completed_count,
              "observation_fields_checked": sum(len(r) for r in observations),
              "summary_groups_checked": len(grouped), "paired_contrasts_checked": len(expected_pairs),
              "historical_mode": historical, "current_source_matches": current_matches,
              "raw_artifact_hashes_verified": len(manifest["runs"]),
              "method": "independent full physical/admission/swap/FIFO replay, chronological queue integration and seed statistics"}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--historical", action="store_true", help="allow current-source differences, retaining recorded build/artifact checks")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.directory, args.historical)
    output = args.output or args.directory/"independent-audit.json"
    require(output.resolve().is_relative_to(ROOT/"results"), "audit output must stay under results/")
    output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Calibrate memory sizing on separate seeds and validate finite-slot blocking."""

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

import networkx as nx

from poqi.analysis.blocking import observe_blocking
from poqi.analysis.erlang import erlang_b
from poqi.reporting import create_output, provenance, write_json
from poqi.simulation import run_simulation

try:
    from .verify_implementation_results import interval, require
except ImportError:
    from verify_implementation_results import interval, require


SCENARIOS = ("direct_cutoff10", "chain_cutoff10", "chain_lossless")
ROOT = Path(__file__).resolve().parents[1]


def specification(name):
    require(name in SCENARIOS, "unknown blocking scenario")
    direct = name.startswith("direct")
    graph = nx.path_graph(2 if direct else 3)
    nx.set_edge_attributes(graph, 1.0, "generation_capacity")
    return graph, {} if direct else {(0, 2): 1.0}, None if name.endswith("lossless") else 10.0


def calibrate(scenario, observations):
    """Offered physical arrival rates times continuous endpoint holding means."""
    graph, _, cutoff = specification(scenario)
    groups = defaultdict(list)
    for observed in observations:
        for row in observed["origins"]:
            groups[row["node"], row["neighbor"]].append(row)
    directed_edges = set(graph.edges) | {(v, u) for u, v in graph.edges}
    require(set(groups) == directed_edges,
            "calibration origin coverage mismatch")
    origins = []
    for (node, neighbor), rows in sorted(groups.items()):
        require(len(rows) == len(observations), "missing calibration origin")
        arrivals = sum(r["cohort_arrivals"] for r in rows)
        censored = sum(r["cohort_censored"] for r in rows)
        require(arrivals > 0, "no holding-time calibration arrivals")
        require(cutoff is None or censored == 0, "bounded calibration cohort is censored")
        holding = sum(r["cohort_departed_holding_sum"] + r["cohort_censored_holding_sum"] for r in rows)
        tau = holding / arrivals
        offered_rate = graph[node][neighbor]["generation_capacity"]
        origins.append({"node": node, "neighbor": neighbor, "offered_rate": offered_rate,
                        "holding_mean": tau, "offered_load": offered_rate * tau,
                        "cohort_arrivals": arrivals, "cohort_censored": censored,
                        "replicate_holding": interval([r["cohort_restricted_mean"] for r in rows])})
    tail = Counter()
    supplied = ["required_capacity_histogram" in observed for observed in observations]
    require(not any(supplied) or all(supplied), "inconsistent calibration arrival-state coverage")
    for observed in observations:
        if "required_capacity_histogram" in observed:
            histogram = observed["required_capacity_histogram"]
            require(len({r["capacity"] for r in histogram}) == len(histogram)
                    and all(type(r["capacity"]) is int and r["capacity"] > 0
                            and type(r["attempts"]) is int and r["attempts"] > 0 for r in histogram),
                    "invalid calibration arrival-state histogram")
            require(sum(r["attempts"] for r in histogram) == observed["offered"],
                    "calibration arrival-state count mismatch")
            tail.update({r["capacity"]: r["attempts"] for r in histogram})
    return {"scenario": scenario, "origins": origins,
            "required_capacity_histogram": [{"capacity": c, "attempts": n} for c, n in sorted(tail.items())],
            "interpretation": "finite-window restricted holding estimate; stationarity unestablished" if cutoff is None
            else "complete admission cohort with bounded physical endpoint holding times"}


def quota(graph, node, neighbor, capacity):
    neighbors = sorted(graph.neighbors(node))
    base, remainder = divmod(capacity, len(neighbors))
    return base + (neighbors.index(neighbor) < remainder)


def predict(calibration, capacity):
    """Reservation-aware marginal Erlang baselines; chain endpoints approximated independent."""
    if capacity is None:
        return {"blocking": 0.0, "tail_blocking": 0.0, "dependence_low": 0.0, "dependence_high": 0.0}
    require(type(capacity) is int and capacity >= 0, "invalid prediction capacity")
    histogram = calibration.get("required_capacity_histogram", [])
    total_attempts = sum(r["attempts"] for r in histogram)
    tail = sum(r["attempts"] for r in histogram if r["capacity"] > capacity) / total_attempts if total_attempts else None
    graph, _, _ = specification(calibration["scenario"])
    losses = {(r["node"], r["neighbor"]): erlang_b(r["offered_load"],
              quota(graph, r["node"], r["neighbor"], capacity)) for r in calibration["origins"]}
    if calibration["scenario"].startswith("direct"):
        # The two endpoint slots are occupied/released together, not independently.
        require(math.isclose(losses[0, 1], losses[1, 0], rel_tol=1e-10, abs_tol=1e-14),
                "direct-control endpoint calibration mismatch")
        b = losses[0, 1]
        return {"blocking": b, "tail_blocking": tail, "dependence_low": b, "dependence_high": b}
    total = sum(graph[u][v]["generation_capacity"] for u, v in graph.edges)
    values = []
    for u, v in graph.edges:
        left, right = losses[u, v], losses[v, u]
        values.append((graph[u][v]["generation_capacity"] / total,
                       left + right - left * right, max(left, right), min(1.0, left + right)))
    return {**dict(zip(("blocking", "dependence_low", "dependence_high"),
                     (sum(row[0] * row[i] for row in values) for i in (1, 2, 3)))), "tail_blocking": tail}


def select_budgets(calibration, target, maximum=2048):
    require(math.isfinite(target) and 0 < target < 1, "invalid blocking target")
    graph, _, _ = specification(calibration["scenario"])
    mean_budget = blocking_budget = tail_budget = None
    has_tail = bool(calibration.get("required_capacity_histogram"))
    for capacity in range(maximum + 1):
        if mean_budget is None and all(quota(graph, r["node"], r["neighbor"], capacity) >= r["offered_load"]
                                       for r in calibration["origins"]):
            mean_budget = capacity
        prediction = predict(calibration, capacity)
        if blocking_budget is None and prediction["blocking"] <= target:
            blocking_budget = capacity
        if has_tail and tail_budget is None and prediction["tail_blocking"] <= target:
            tail_budget = capacity
        if mean_budget is not None and blocking_budget is not None and (not has_tail or tail_budget is not None):
            break
    require(mean_budget is not None and blocking_budget is not None and (not has_tail or tail_budget is not None),
            "sizing search exceeded guard")
    base = [8, 10, 12, 16, 17, 18, 20, 24] if calibration["scenario"].startswith("direct") else [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 64]
    selected = [mean_budget, blocking_budget, max(0, blocking_budget - 1), blocking_budget + 1]
    if tail_budget is not None:
        selected += [tail_budget, max(0, tail_budget - 1), tail_budget + 1]
    capacities = sorted(set(base + selected))
    return {"mean_budget": mean_budget, "erlang_budget": blocking_budget, "tail_budget": tail_budget,
            "capacities": [*capacities, None]}


def run_case(output, scenario, phase, seed, capacity, horizon, warmup):
    graph, demand, cutoff = specification(scenario)
    label = "unlimited" if capacity is None else str(capacity)
    identifier = f"{scenario}-{phase}-s{seed}-c{label}"
    started = perf_counter()
    data = run_simulation(graph, demand, memory_slots=capacity, cutoff_time=cutoff,
                          distillation_pairs=1, horizon=horizon, seed=seed,
                          ticks_per_time_unit=1000000, admission_policy="reserved",
                          swap_policy="none" if scenario.startswith("direct") else "balancing",
                          record_events=True).to_dict()
    cohort_end = horizon / 2 if cutoff is None else horizon - cutoff
    observed = observe_blocking(data, warmup=warmup, cohort_end=cohort_end,
                                physical_neighbors={n: list(graph.neighbors(n)) for n in graph})
    row = {"id": identifier, "scenario": scenario, "phase": phase, "seed": seed,
           "capacity": capacity, "horizon": horizon, "warmup": warmup, "cohort_end": cohort_end,
           "wall_seconds": perf_counter() - started, "artifact": f"runs/{identifier}.json.gz"}
    with gzip.open(output / row["artifact"], "wt", encoding="utf-8") as stream:
        json.dump({"case": row, "simulation": data, "observed": observed}, stream, allow_nan=False)
    print(f"{identifier}: block={observed['blocking_probability']:.5f}, throughput={observed['throughput']:.4f}", flush=True)
    return row, observed


def run_suite(output, *, horizon=4000, warmup=1000, calibration_runs=5, validation_runs=10,
              target=.01, calibration_seed=1271, validation_seed=3271):
    require(horizon > 40 and 0 <= warmup < horizon / 2 - 10, "invalid horizon/warmup")
    require(type(calibration_runs) is int and calibration_runs >= 2 and type(validation_runs) is int and validation_runs >= 2,
            "at least two repetitions required")
    require(type(calibration_seed) is int and calibration_seed >= 0 and type(validation_seed) is int and validation_seed >= 0,
            "invalid seed")
    require(math.isfinite(target) and 0 < target < 1, "invalid blocking target")
    calibration_seeds = list(range(calibration_seed, calibration_seed + calibration_runs))
    validation_seeds = list(range(validation_seed, validation_seed + validation_runs))
    require(not set(calibration_seeds) & set(validation_seeds), "calibration and validation seeds overlap")
    output = create_output(output)
    (output / "runs").mkdir()
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (Path(__file__).resolve(), ROOT / "src/poqi/analysis/blocking.py", ROOT / "src/poqi/analysis/erlang.py")}
    manifest = {**provenance(), "status": "running", "horizon": horizon, "warmup": warmup,
                "calibration_seeds": calibration_seeds, "validation_seeds": validation_seeds,
                "target": target, "scenarios": {}, "runs": [], "source_sha256": hashes,
                "protocol": "D=1; empty initialization; reserved admission; fixed horizons; calibration/validation seeds disjoint; same exogenous inputs across capacities",
                "rate_units": "abstract time unit", "intervals": "pointwise 95% Student-t across independent seeds; no event-wise independence assumption"}
    write_json(output / "manifest.json", manifest)
    try:
        for scenario in SCENARIOS:
            observations = []
            for seed in calibration_seeds:
                row, observed = run_case(output, scenario, "calibration", seed, None, horizon, warmup)
                observations.append(observed)
                manifest["runs"].append(row)
                write_json(output / "manifest.json", manifest)
            calibration = calibrate(scenario, observations)
            design = {**select_budgets(calibration, target), "calibration": calibration}
            manifest["scenarios"][scenario] = design
            if scenario == "chain_lossless":
                for seed in calibration_seeds:
                    row, _ = run_case(output, scenario, "short_calibration", seed, None, horizon / 2, warmup / 2)
                    manifest["runs"].append(row)
                    write_json(output / "manifest.json", manifest)
            for capacity in design["capacities"]:
                for seed in validation_seeds:
                    row, _ = run_case(output, scenario, "validation", seed, capacity, horizon, warmup)
                    manifest["runs"].append(row)
                    write_json(output / "manifest.json", manifest)
        manifest["status"] = "completed"
        write_json(output / "manifest.json", manifest)
    except Exception as error:
        manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(output / "manifest.json", manifest)
        raise
    return output


def build_report(source):
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "completed", "experiment is incomplete")
    calibration_seeds, validation_seeds = manifest["calibration_seeds"], manifest["validation_seeds"]
    require(all(len(seeds) >= 2 and len(set(seeds)) == len(seeds)
                and all(type(seed) is int and seed >= 0 for seed in seeds)
                for seeds in (calibration_seeds, validation_seeds)), "invalid or duplicate seed lists")
    require(not set(calibration_seeds) & set(validation_seeds), "calibration/validation overlap")
    require(set(manifest["scenarios"]) == set(SCENARIOS), "scenario coverage mismatch")
    expected = {(s, "calibration", seed, None) for s in SCENARIOS for seed in calibration_seeds}
    expected |= {("chain_lossless", "short_calibration", seed, None) for seed in calibration_seeds}
    expected |= {(s, "validation", seed, c) for s in SCENARIOS for seed in validation_seeds
                 for c in manifest["scenarios"][s]["capacities"]}
    cases, signatures, observations = {}, {}, []
    for case in manifest["runs"]:
        key = (case["scenario"], case["phase"], case["seed"], case["capacity"])
        require(key in expected and key not in cases, "unexpected or duplicate experiment case")
        with gzip.open(source / case["artifact"], "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
        require(saved["case"] == case, "case/manifest mismatch")
        data = saved["simulation"]
        short = case["phase"] == "short_calibration"
        require(case["horizon"] == manifest["horizon"] / (2 if short else 1)
                and case["warmup"] == manifest["warmup"] / (2 if short else 1), "protocol horizon mismatch")
        graph, demand, cutoff = specification(case["scenario"])
        require(data["distillation_pairs"] == 1 and data["initial_pairs"] == 0
                and data["cutoff_time"] == cutoff and data["admission_policy"] == "reserved"
                and data["swap_policy"] == ("none" if not demand else "balancing")
                and data["ticks_per_time_unit"] == 1000000 and data["time_unit"] == "abstract",
                "simulation protocol mismatch")
        expected_cohort_end = case["horizon"] / 2 if cutoff is None else case["horizon"] - cutoff
        require(case["cohort_end"] == expected_cohort_end, "cohort protocol mismatch")
        require(data["seed"] == case["seed"] and data["horizon"] == case["horizon"], "seed/horizon mismatch")
        require(all(r["memory_slots"] == case["capacity"] for r in data["occupancy_by_node"]), "capacity mismatch")
        obs = observe_blocking(data, warmup=case["warmup"], cohort_end=case["cohort_end"],
                               physical_neighbors={n: list(graph.neighbors(n)) for n in graph})
        require(obs == saved["observed"], "saved observations do not match event replay")
        if case["phase"] == "validation":
            match = (case["scenario"], case["seed"])
            require(match not in signatures or signatures[match] == obs["exogenous_signature"], "unmatched inputs across capacities")
            signatures[match] = obs["exogenous_signature"]
        cases[key] = obs
        observations.append({**case, "offered": obs["offered"], "rejected": obs["rejected"],
                             "blocking_probability": obs["blocking_probability"], "throughput": obs["throughput"],
                             "hard_slot_rejections": obs["rejections_by_reason"].get("hard_slots", 0),
                             "reservation_rejections": obs["rejections_by_reason"].get("neighbor_reservation", 0)})
    require(set(cases) == expected, "missing experiment cases")
    report = {"sources": str(source), "protocol": manifest["protocol"], "target": manifest["target"],
              "horizon": manifest["horizon"], "warmup": manifest["warmup"], "intervals": manifest["intervals"],
              "calibration_seeds": calibration_seeds, "validation_seeds": validation_seeds,
              "validated_runs": len(cases), "summary": [], "sizing": [], "calibration": [],
              "origins": [], "nodes": [], "observations": observations}
    for scenario in SCENARIOS:
        calibration = calibrate(scenario, [cases[scenario, "calibration", seed, None] for seed in calibration_seeds])
        design = select_budgets(calibration, manifest["target"])
        require(design == {k: manifest["scenarios"][scenario][k] for k in design}, "calibration/design mismatch")
        report["calibration"].append(calibration)
        if scenario == "chain_lossless":
            report["short_calibration"] = calibrate(scenario, [cases[scenario, "short_calibration", seed, None] for seed in calibration_seeds])
        summaries = []
        for capacity in design["capacities"]:
            rows = [cases[scenario, "validation", seed, capacity] for seed in validation_seeds]
            summary = {"scenario": scenario, "capacity": capacity, "n": len(rows), **predict(calibration, capacity)}
            for metric in ("blocking_probability", "throughput"):
                summary[metric] = interval([r[metric] for r in rows])
            for reason in ("hard_slots", "neighbor_reservation"):
                summary[reason] = interval([r["rejections_by_reason"].get(reason, 0) / r["offered"] for r in rows])
            summary["zero_completion_runs"] = sum(r["completed_requests"] == 0 for r in rows)
            summary["total_offered"] = sum(r["offered"] for r in rows)
            summaries.append(summary)
            report["summary"].append(summary)
            for seed, obs in zip(validation_seeds, rows):
                for kind in ("nodes", "origins"):
                    report[kind].extend({"scenario": scenario, "capacity": capacity, "seed": seed, **r} for r in obs[kind])
        finite = [r for r in summaries if r["capacity"] is not None]
        attained = [r["capacity"] for r in finite if r["blocking_probability"]["mean"] <= manifest["target"]]
        upper_met = [r["capacity"] for r in finite if r["blocking_probability"]["ci95"][1] <= manifest["target"]]
        selected = {"scenario": scenario, "mean_budget": design["mean_budget"], "erlang_budget": design["erlang_budget"],
                    "tail_budget": design["tail_budget"],
                    "smallest_tested_mean_meets_target": min(attained) if attained else None,
                    "smallest_tested_upper_ci_meets_target": min(upper_met) if upper_met else None,
                    "prediction_mae": sum(abs(r["blocking"] - r["blocking_probability"]["mean"]) for r in finite) / len(finite),
                    "tail_prediction_mae": sum(abs(r["tail_blocking"] - r["blocking_probability"]["mean"]) for r in finite) / len(finite)}
        for name in ("mean", "erlang", "tail"):
            row = next(r for r in finite if r["capacity"] == selected[f"{name}_budget"])
            selected[f"{name}_observed_blocking"] = row["blocking_probability"]
            selected[f"{name}_predicted_blocking"] = row["tail_blocking" if name == "tail" else "blocking"]
            selected[f"{name}_observed_throughput"] = row["throughput"]
        report["sizing"].append(selected)
    return report


def write_report(report, output):
    output = create_output(output)
    write_json(output / "blocking.json", report)
    for name in ("observations", "summary", "sizing", "origins", "nodes"):
        rows = report[name]
        with (output / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(3, 2, figsize=(12, 11), constrained_layout=True)
    for index, scenario in enumerate(SCENARIOS):
        rows = sorted((r for r in report["summary"] if r["scenario"] == scenario and r["capacity"] is not None), key=lambda r: r["capacity"])
        x = [r["capacity"] for r in rows]
        for ax, metric, title in ((axes[index, 0], "blocking_probability", "Rejected generation fraction"),
                                  (axes[index, 1], "throughput", "Completed requests / time unit")):
            y = [r[metric]["mean"] for r in rows]
            errors = [[r[metric]["mean"] - r[metric]["ci95"][0] for r in rows],
                      [r[metric]["ci95"][1] - r[metric]["mean"] for r in rows]]
            ax.errorbar(x, y, yerr=errors, fmt="o-", capsize=3, label="Measured: mean and 95% t CI")
            ax.set(xlabel="Slots per node", ylabel=title, title=scenario.replace("_", " "))
            if scenario.startswith("chain"):
                ax.set_xscale("symlog", linthresh=1, base=2)
                ax.set_xlabel("Slots per node (log scale)")
            ax.grid(alpha=.2)
        axes[index, 0].plot(x, [r["blocking"] for r in rows], "s--", label="Erlang baseline")
        axes[index, 0].plot(x, [r["tail_blocking"] for r in rows], "^--", label="Unlimited-trajectory tail baseline")
        axes[index, 0].axhline(report["target"], color="black", linestyle=":", label=f"{100 * report['target']:g}% target")
        axes[index, 0].set_yscale("symlog", linthresh=.001)
        sizing = next(r for r in report["sizing"] if r["scenario"] == scenario)
        axes[index, 0].axvline(sizing["mean_budget"], color="#999999", linestyle=":", label="Mean-sized budget")
        axes[index, 0].axvline(sizing["erlang_budget"], color="#8c564b", linestyle=":", label="Erlang-sized budget")
        axes[index, 0].axvline(sizing["tail_budget"], color="#2ca02c", linestyle=":", label="Tail-sized budget")
        baseline = next(r for r in report["summary"] if r["scenario"] == scenario and r["capacity"] is None)
        axes[index, 1].axhline(baseline["throughput"]["mean"], linestyle="--", color="#777777", label="Unlimited policy")
        if scenario.startswith("direct"):
            axes[index, 1].text(.5, .55, "No demand: exact loss-system control", transform=axes[index, 1].transAxes, ha="center")
        axes[index, 0].legend(fontsize=7)
        axes[index, 1].legend(fontsize=8)
    fig.suptitle("Memory sizing: independent calibration and validation seeds")
    fig.savefig(output / "blocking.png", dpi=170)
    plt.close(fig)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-runs", type=Path, help="Rebuild analysis from a completed saved experiment")
    parser.add_argument("--horizon", type=float, default=4000)
    parser.add_argument("--warmup", type=float, default=1000)
    parser.add_argument("--calibration-runs", type=int, default=5)
    parser.add_argument("--validation-runs", type=int, default=10)
    parser.add_argument("--target", type=float, default=.01)
    args = parser.parse_args()
    if args.from_runs:
        destination = write_report(build_report(args.from_runs), args.output)
    else:
        source = run_suite(args.output, horizon=args.horizon, warmup=args.warmup,
                           calibration_runs=args.calibration_runs, validation_runs=args.validation_runs,
                           target=args.target)
        destination = write_report(build_report(source), source / "report")
    print(f"Validated experiment and wrote {destination}")


if __name__ == "__main__":
    main()

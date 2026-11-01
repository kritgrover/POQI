"""Small controlled sweeps; finite-cutoff runs retain a separate LP label."""

import csv
from itertools import product
import math
from numbers import Real
from statistics import mean, stdev

from scipy.stats import t

from ..lp import solve_throughput, size_memory
from ..reporting import create_output, manifest, write_json


def _values(settings, name, default, *, positive=False, fraction=False, unlimited=False):
    values = settings.get(name, default)
    if not isinstance(values, list) or not values:
        raise ValueError(f"sweep.{name} must be a nonempty list")
    for value in values:
        if value is None and unlimited:
            continue
        if (isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
                or value < 0 or (positive and value == 0) or (fraction and value > 1)):
            raise ValueError(f"invalid sweep.{name} value: {value!r}")
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate sweep.{name} values")
    return values


def _write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _interval(values, expected):
    if len(values) != expected:
        return None, None, None
    center = mean(values)
    if len(values) < 2:
        return center, None, None
    half = float(t.ppf(0.975, len(values) - 1)) * stdev(values) / math.sqrt(len(values))
    return center, center - half, center + half


def _plot(output, lp_rows, summaries):
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except ImportError:
        return "not generated: install poqi[simulation] for matplotlib"
    fig, axes = plt.subplots(1, 2 if summaries else 1, figsize=(11 if summaries else 6, 4), squeeze=False)
    ax = axes[0, 0]
    groups = sorted({(row["residence_factor"], row["demand_factor"]) for row in lp_rows})
    for tau, load in groups:
        points = sorted((r["memory_slots"], r["alpha"]) for r in lp_rows
                        if r["residence_factor"] == tau and r["demand_factor"] == load
                        and r["memory_slots"] is not None and r["alpha"] is not None)
        if points:
            ax.plot(*zip(*points), marker="o", label=f"tau × {tau}, demand × {load}")
    ax.set(xlabel="Uniform mean memory budget", ylabel="Proportional satisfaction alpha", ylim=(0, 1.05),
           title="Conditional prescribed-tau LP")
    ax.legend(fontsize="small")
    if summaries:
        ax = axes[0, 1]
        for load in sorted({row["demand_factor"] for row in summaries}):
            rows = sorted((r for r in summaries if r["demand_factor"] == load
                           and r["memory_slots"] is not None and r["throughput_mean"] is not None),
                          key=lambda r: r["memory_slots"])
            if rows:
                ax.plot([r["memory_slots"] for r in rows], [r["throughput_mean"] for r in rows],
                        marker="o", label=f"demand × {load}")
                for row in rows:
                    if row["throughput_ci_low"] is not None:
                        ax.vlines(row["memory_slots"], row["throughput_ci_low"], row["throughput_ci_high"])
            reference = next((r for r in summaries if r["demand_factor"] == load
                              and r["memory_slots"] is None and r["throughput_mean"] is not None), None)
            if reference is not None:
                ax.axhline(reference["throughput_mean"], linestyle="--", alpha=0.7,
                           label=f"unlimited policy, demand × {load}")
        ax.set(xlabel="Uniform hard slots per node", ylabel="Completed requests / time unit",
               title="SeQUeNCe policy: replicate means, 95% t CI")
        ax.legend(fontsize="small")
    fig.tight_layout()
    fig.savefig(output / "memory-sweep.png", dpi=150)
    plt.close(fig)
    return "memory-sweep.png"


def run_memory_sweep(config, output_path):
    state = {}
    try:
        return _run_memory_sweep(config, output_path, state)
    except Exception as error:
        # Finalize only directories created by this invocation. Validation errors
        # and attempted overwrites must never mutate an existing experiment.
        if "output" in state:
            path = state["output"] / "manifest.json"
            data = state.get("manifest", {})
            data.update(status="failed", error=f"{type(error).__name__}: {error}")
            try:
                write_json(path, data)
            except OSError:
                pass  # Preserve the original failure if the disk itself failed.
        raise


def _run_memory_sweep(config, output_path, state):
    settings = config.sweep
    allowed = {"memory_slots", "fractions", "residence_factors", "demand_factors", "simulate", "replicates", "seed"}
    if set(settings) - allowed:
        raise ValueError(f"Unknown sweep keys: {sorted(set(settings) - allowed)}")
    budgets = _values(settings, "memory_slots", [0, 1, 2, 4, 8, None], unlimited=True)
    if None not in budgets:
        budgets = [*budgets, None]
    fractions = _values(settings, "fractions", [0.5, 0.9, 0.95, 0.99], fraction=True)
    tau_factors = _values(settings, "residence_factors", [1], positive=True)
    demand_factors = _values(settings, "demand_factors", [1], positive=True)
    simulate = settings.get("simulate", False)
    if not isinstance(simulate, bool):
        raise ValueError("sweep.simulate must be boolean")
    replicates = settings.get("replicates", 3)
    seed = settings.get("seed", config.simulation.get("seed", 271))
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValueError("sweep.replicates must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("sweep.seed must be a nonnegative integer")
    if simulate and any(m is not None and int(m) != m for m in budgets):
        raise ValueError("simulation sweeps require integer hard memory budgets")
    if simulate and config.simulation.get("trace") is not None:
        raise ValueError("replicate sweeps require stochastic inputs; use simulate for deterministic traces")
    output = create_output(output_path)
    state["output"] = output
    (output / "runs").mkdir()
    run_manifest = manifest(config, "experiments memory-sweep")
    state["manifest"] = run_manifest
    run_manifest.update(sweep_settings={"memory_slots": budgets, "fractions": fractions,
                        "residence_factors": tau_factors, "demand_factors": demand_factors,
                        "simulate": simulate, "replicates": replicates, "seed": seed},
                        warmup=0, intervals="95% Student-t over independent replicates; undefined on any failure",
                        comparison="Same policy with unlimited slots; LP is lossless and conditional on prescribed tau",
                        random_streams="Fixed graph/demand: seed+replicate shared across memory budgets; independent per-input streams")
    write_json(output / "manifest.json", run_manifest)
    lp_rows, sizing_rows, simulation_rows, summaries = [], [], [], []
    failures = []
    baselines = {}
    for variant, (tau_factor, demand_factor) in enumerate(product(tau_factors, demand_factors)):
        demand = {pair: value * demand_factor for pair, value in config.demand_rate.items()}
        tau = ({pair: value * tau_factor for pair, value in config.mean_residence_time.items()}
               if isinstance(config.mean_residence_time, dict) else config.mean_residence_time * tau_factor)
        kwargs = dict(mean_residence_time=tau, distillation_pairs=config.distillation_pairs, balance_mode=config.balance_mode)
        baseline = solve_throughput(config.graph, demand, memory_slots=None, **kwargs)
        baselines[demand_factor] = baseline
        write_json(output / "runs" / f"lp-{variant}-unlimited.json", baseline.to_dict())
        for index, budget in enumerate(budgets):
            result = baseline if budget is None else solve_throughput(config.graph, demand, memory_slots=budget, **kwargs)
            write_json(output / "runs" / f"lp-{variant}-{index}.json", result.to_dict())
            if not result.success:
                failures.append(f"LP variant {variant}, budget {budget}: {result.status}")
            lp_rows.append({"residence_factor": tau_factor, "demand_factor": demand_factor,
                            "memory_slots": budget, "status": result.status, "alpha": result.alpha,
                            "alpha_infinity": baseline.alpha,
                            "fraction_of_unlimited": result.alpha / baseline.alpha if result.success and baseline.success and baseline.alpha > 0 else None,
                            "total_completion": result.total_completion,
                            "assembly_seconds": result.timings.get("assembly_seconds"),
                            "solve_seconds": result.timings.get("solve_seconds")})
        for fraction in fractions:
            result = size_memory(config.graph, demand, fraction=fraction, **kwargs)
            write_json(output / "runs" / f"size-{variant}-{fraction}.json", result.to_dict())
            if not result.success and result.status != "nonserviceable_demand":
                failures.append(f"Sizing variant {variant}, fraction {fraction}: {result.status}")
            sizing_rows.append({"residence_factor": tau_factor, "demand_factor": demand_factor,
                                "fraction": fraction, "status": result.status,
                                "alpha_infinity": result.alpha_infinity,
                                "target_alpha": result.target_alpha, "mean_memory_budget": result.memory_budget})
    if simulate:
        from ..simulation.sequence_adapter import run_simulation
        for load_index, demand_factor in enumerate(demand_factors):
            demand = {pair: value * demand_factor for pair, value in config.demand_rate.items()}
            baseline = baselines[demand_factor]
            for budget_index, budget in enumerate(budgets):
                group = []
                for replicate in range(replicates):
                    kwargs = dict(config.simulation)
                    kwargs.update(seed=seed + replicate, record_events=True)
                    filename = f"simulation-{load_index}-{budget_index}-{replicate}.json"
                    row = {"demand_factor": demand_factor, "memory_slots": budget, "replicate": replicate,
                           "seed": seed + replicate, "status": "failed", "throughput": None,
                           "minimum_pair_satisfaction": None, "unserved_requests": None,
                           "mean_completed_latency": None, "artifact": f"runs/{filename}"}
                    try:
                        data = run_simulation(config.graph, demand, memory_slots=budget,
                                              distillation_pairs=config.distillation_pairs,
                                              time_unit=config.time_unit, **kwargs).to_dict()
                        satisfaction = min(r["throughput"] / r["demand_rate"] for r in data["service_by_pair"] if r["demand_rate"] > 0)
                        matched = config.simulation.get("cutoff_time") is None and baseline.success and baseline.alpha > 0
                        data["lp_target_checks"] = [{"fraction": eta,
                            "interpretation": "lossless conditional LP target" if matched else "unmatched loss assumptions or nonserviceable baseline",
                            "proportional_target_met": satisfaction >= eta * baseline.alpha if matched else None,
                            "aggregate_target_met": data["throughput"] >= eta * baseline.alpha * sum(demand.values()) if matched else None}
                            for eta in fractions]
                        write_json(output / "runs" / filename, data)
                        row.update(status="completed", throughput=data["throughput"],
                                   minimum_pair_satisfaction=satisfaction, unserved_requests=data["unserved_requests"],
                                   mean_completed_latency=data["mean_completed_latency"])
                    except (ValueError, RuntimeError, AssertionError) as error:
                        failure = f"simulation load {demand_factor}, budget {budget}, replicate {replicate}: {error}"
                        failures.append(failure)
                        write_json(output / "runs" / filename, {"status": "failed", "error": failure,
                                   "memory_slots": budget, "seed": seed + replicate, "configuration": config.raw})
                    group.append(row)
                    simulation_rows.append(row)
                center, low, high = _interval([r["throughput"] for r in group if r["status"] == "completed"], replicates)
                summaries.append({"demand_factor": demand_factor, "memory_slots": budget,
                                  "replicates": replicates, "completed_replicates": sum(r["status"] == "completed" for r in group),
                                  "throughput_mean": center, "throughput_ci_low": low, "throughput_ci_high": high})
    _write_csv(output / "lp.csv", lp_rows, list(lp_rows[0]))
    _write_csv(output / "sizing.csv", sizing_rows, list(sizing_rows[0]))
    if simulation_rows:
        _write_csv(output / "simulation.csv", simulation_rows, list(simulation_rows[0]))
        _write_csv(output / "summary.csv", summaries, list(summaries[0]))
    run_manifest.update(status="complete" if not failures else "incomplete", failures=failures,
                        plot=_plot(output, lp_rows, summaries))
    write_json(output / "manifest.json", run_manifest)
    return {"status": run_manifest["status"], "output": str(output), "lp_runs": len(lp_rows),
            "sizing_runs": len(sizing_rows), "simulation_runs": len(simulation_rows), "failures": failures}

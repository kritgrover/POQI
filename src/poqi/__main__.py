"""Command line entry point; all commands run from the POQI project root."""

import argparse
import json
import sys

from .config import load_config
from .reporting import create_output, manifest, write_json


def parser():
    root = argparse.ArgumentParser(prog="poqi", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    lp = commands.add_parser("lp", help="Lossless rate and mean-memory benchmarks")
    lp_commands = lp.add_subparsers(dest="operation", required=True)
    for name in ("solve", "min-generation", "size-memory"):
        command = lp_commands.add_parser(name)
        command.add_argument("--config", required=True)
        command.add_argument("--output", help="New root-owned output directory (otherwise JSON to stdout)")
        if name == "size-memory":
            command.add_argument("--fraction", type=float, default=0.9)
    simulation = commands.add_parser("simulate", help="Run the root model on SeQUeNCe")
    simulation.add_argument("--backend", choices=["sequence"], default="sequence")
    simulation.add_argument("--config", required=True)
    simulation.add_argument("--output", required=True)
    experiments = commands.add_parser("experiments")
    experiment_commands = experiments.add_subparsers(dest="operation", required=True)
    sweep = experiment_commands.add_parser("memory-sweep")
    sweep.add_argument("--config", required=True)
    sweep.add_argument("--output", required=True)
    commands.add_parser("sequence-smoke", help="Check the local SeQUeNCe import and execute an event")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    output = None
    run_manifest = None
    try:
        if args.command == "sequence-smoke":
            from .simulation.sequence_adapter import sequence_smoke
            print(json.dumps(sequence_smoke(), indent=2, allow_nan=False))
            return 0
        config = load_config(args.config)
        if args.command == "experiments":
            from .experiments.memory_sweep import run_memory_sweep
            report = run_memory_sweep(config, args.output)
            print(json.dumps(report, indent=2, allow_nan=False))
            return 0 if report["status"] == "complete" else 1
        if args.output:
            output = create_output(args.output)
            run_manifest = manifest(config, " ".join(sys.argv[1:] if argv is None else argv))
            write_json(output / "manifest.json", run_manifest)
        if args.command == "lp":
            from .lp import solve_min_generation, solve_throughput, size_memory
            kwargs = config.lp_kwargs()
            if args.operation == "size-memory":
                kwargs.pop("memory_slots")
                result = size_memory(config.graph, config.demand_rate, fraction=args.fraction, **kwargs)
            else:
                solve = solve_throughput if args.operation == "solve" else solve_min_generation
                result = solve(config.graph, config.demand_rate, **kwargs)
            payload = result.to_dict()
            successful = result.success
        else:
            from .simulation.sequence_adapter import run_simulation
            result = run_simulation(config.graph, config.demand_rate,
                                    memory_slots=config.memory_slots,
                                    distillation_pairs=config.distillation_pairs,
                                    time_unit=config.time_unit, **config.simulation)
            payload = result.to_dict()
            successful = True
        if output:
            write_json(output / "result.json", payload)
            run_manifest["status"] = "complete" if successful else "failed"
            write_json(output / "manifest.json", run_manifest)
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0 if successful else 1
    except (ValueError, OSError, ImportError, RuntimeError, AssertionError) as error:
        if output is not None and run_manifest is not None:
            run_manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
            write_json(output / "manifest.json", run_manifest)
        print(f"poqi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


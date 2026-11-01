"""Reproducible, root-owned experiment artifacts."""

from datetime import datetime, timezone
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess


ROOT = Path(__file__).resolve().parents[2]
AUTHOR_PYTHON_REVISION = "7c57be549c275509b1674aaab3f7341c955041db"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def create_output(path):
    output = Path(path).resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        raise ValueError("Results must be in a new directory below the POQI root")
    protected = {"sequence", "quantum-network", ".git", ".venv", ".agents", ".codex", ".aws"}
    if output.relative_to(ROOT).parts[0].casefold() in protected:
        raise ValueError("Results cannot be written inside submodules, environments, or repository metadata")
    output.mkdir(parents=True, exist_ok=False)
    return output


def provenance():
    revisions = {}
    for label, directory in (("poqi", ROOT), ("sequence", ROOT / "SeQUeNCe"),
                             ("author_checkout", ROOT / "quantum-network")):
        def git(*args):
            try:
                return subprocess.run(["git", "-C", str(directory), *args],
                                      capture_output=True, text=True, check=True).stdout.strip()
            except (OSError, subprocess.CalledProcessError):
                return None
        revisions[label] = {"revision": git("rev-parse", "HEAD"),
                            "working_tree_status": git("status", "--short")}
    versions = {}
    for package in ("poqi", "numpy", "scipy", "networkx", "sequence", "qutip"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {"created_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "platform": platform.platform(),
            "packages": versions, "sources": revisions,
            "historical_author_python_revision": AUTHOR_PYTHON_REVISION,
            "solver": "scipy.optimize.linprog / HiGHS"}


def manifest(config, command):
    return {**provenance(), "command": command, "configuration": config.raw,
            "time_unit": config.time_unit,
            "mean_residence_time_source": config.residence_time_source,
            "lp_interpretation": "prescribed-tau conditional average-memory benchmark",
            "lp_losses": "lossless; cutoff is simulated separately",
            "status": "running"}


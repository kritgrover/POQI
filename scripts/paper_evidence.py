"""Build or verify the paper evidence inventory using only the standard library."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence/release.json"
TAG = "poqi-finite-memory-paper-v1"
TEXT_SUFFIXES = {".md", ".csv", ".json", ".jsonl", ".py", ".toml", ".kt"}


def fingerprint(path):
    content = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def create_manifest(source_ref):
    sources = [
        "README.md", "docs/finite-memory-model.md", "pyproject.toml", "Chain_Capacity.md",
        "Guarded_Chain_Theorem.md", "Saturated_Chain_Theorem.md", "Lockup_Extensions.md",
        "Recovery_Baseline.md", "Matched_Protocol.md", "Matched_Results.md",
        "QCAST_Concurrent_Results.md", "Guarded_Diamond_Results.md",
        "scripts/chain_capacity.py", "scripts/chain_tandem_check.py", "scripts/dead_state_search.py",
        "scripts/guarded_chain_check.py", "scripts/saturated_chain_check.py", "scripts/two_slot_chain_check.py",
        "scripts/two_slot_lock_probability.py", "scripts/two_slot_swap_failure.py",
        "scripts/saturated_long_chain_sim.py", "scripts/cutoff_outage_analysis.py",
        "scripts/recovery_baseline.py", "scripts/matched_srs.py", "scripts/matched_srs_report.py",
        "scripts/srs_protocol.py", "scripts/matched_lossless_diagnostic.py", "scripts/matched_order_holdout.py",
        "scripts/theory_evidence.py", "scripts/paper_evidence.py", "scripts/plot_heldout_order.py",
        "tests/test_srs_protocol.py", "tests/test_matched_srs.py", "tests/test_lossless_cycle_order.py",
    ]
    required = ["theory/uncapped-freezes.json", "theory/tandem.json", "recovery/lockup-scan.jsonl",
                "recovery/reserved/runs.json.gz", "recovery/tail-drop/runs.json.gz",
                "matched/runs.jsonl.gz", "matched/primary.pdf", "matched/paired.csv",
                "matched-lossless/holdout/protocol.json", "matched-lossless/holdout/paired.csv",
                "matched-lossless/heldout-order.pdf"]
    for name in required:
        if not (ROOT/"evidence"/name).is_file():
            raise FileNotFoundError(name)
    paths = {ROOT/name for name in sources}
    paths.update((ROOT/"src/poqi").rglob("*.py"))
    paths.update((ROOT/"scripts").glob("*recovery*.py"))
    paths.update(p for p in (ROOT/"evidence").rglob("*") if p.is_file() and p != MANIFEST)
    hashes = {p.relative_to(ROOT).as_posix(): fingerprint(p) for p in sorted(paths)}
    commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{source_ref}^{{commit}}"],
                                     cwd=ROOT, text=True).strip()
    for name in ("matched", "theory", "recovery/reserved", "recovery/tail-drop"):
        cohort = json.loads((ROOT/"evidence"/name/"manifest.json").read_text(encoding="utf-8"))
        for source, expected in cohort["source_sha256_lf"].items():
            blob = subprocess.check_output(["git", "cat-file", "blob", f"{commit}:{source}"], cwd=ROOT)
            if hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() != expected:
                raise ValueError(f"{name} input differs from committed source: {source}")
    submodules = {}
    for module in ("SeQUeNCe", "quantum-network"):
        # Use the pinned gitlink from the parent repository.
        submodules[module] = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{module}"], cwd=ROOT, text=True).strip()
    release = {"tag": TAG, "primary_studies_source_commit": commit,
               "hash": "SHA-256; CRLF normalized to LF for text inputs",
               "submodule_commits": submodules, "files": hashes}
    MANIFEST.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8", newline="\n")


def verify():
    release = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name, digest in release["files"].items():
        path = ROOT / name
        if not path.is_file() or fingerprint(path) != digest:
            raise ValueError(f"missing or changed release file: {name}")
    print(f"Verified {len(release['files'])} files for {release['tag']}.")


def archive(target):
    """Create a portable ZIP from the tag and its gitlinks, including the simulator."""
    if target.exists():
        raise FileExistsError(target)
    commit = subprocess.check_output(["git", "rev-parse", "--verify", f"{TAG}^{{commit}}"],
                                     cwd=ROOT, text=True).strip()
    manifest = json.loads(subprocess.check_output(["git", "show", f"{commit}:evidence/release.json"], cwd=ROOT))
    trees = [(ROOT, commit, "")]
    for module, expected in manifest["submodule_commits"].items():
        pinned = subprocess.check_output(["git", "rev-parse", f"{commit}:{module}"], cwd=ROOT, text=True).strip()
        if pinned != expected:
            raise ValueError(f"tag and manifest disagree on {module}")
        trees.append((ROOT/module, pinned, f"{module}/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as staging:
        tmp = Path(staging) / "release.zip"
        write_archive(tmp, commit, trees, manifest)
        tmp.rename(target)
    print(f"{target.name} from {commit}: {hashlib.sha256(target.read_bytes()).hexdigest()}")


def write_archive(tmp, commit, trees, manifest):
    with ZipFile(tmp, "x", compression=ZIP_DEFLATED) as out:
        out.comment = commit.encode("ascii")
        for directory, revision, prefix in trees:
            snapshot = subprocess.check_output(["git", "archive", "--format=zip", revision], cwd=directory)
            with ZipFile(io.BytesIO(snapshot)) as tree:
                for member in tree.infolist():
                    if member.is_dir():
                        continue
                    data = tree.read(member)
                    member.filename = prefix + member.filename
                    out.writestr(member, data)
    with ZipFile(tmp) as bundle:
        if bad := bundle.testzip():
            raise ValueError(f"corrupt archive member: {bad}")
        for name, expected in manifest["files"].items():
            content = bundle.read(name)
            if Path(name).suffix in TEXT_SUFFIXES:
                content = content.replace(b"\r\n", b"\n")
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"archive checksum mismatch: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="create the final release inventory before tagging")
    parser.add_argument("--primary-source-ref", default="HEAD", help="revision checked against original run inputs")
    parser.add_argument("--archive", type=Path, help="make a ZIP of the tagged tree and pinned submodules")
    args = parser.parse_args()
    if args.write:
        create_manifest(args.primary_source_ref)
    verify()
    if args.archive:
        archive(args.archive)

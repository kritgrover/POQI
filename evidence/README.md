# Finite-memory POQI paper artifact

The local release tag is `poqi-finite-memory-paper-v1`. The raw observations, paired inputs, theory checks and plotting code are included in the parent repository. [Release checksums](release.json)

| Study | Released observations | Interpretation |
| --- | --- | --- |
| Queued SRS comparison | [Seed records](matched/runs.jsonl.gz), [design and run manifest](matched/manifest.json), [cell estimates](matched/cells.csv), [paired differences](matched/paired.csv), [rare-demand sensitivity](matched/background-sensitivity.csv), [vector figure](matched/primary.pdf) | Discrete slots, matched demand and potential link successes, finite lifetimes. Each compressed line is one seed and arm with per-pair interruption lengths and censoring. |
| Lossless scheduling follow-up | [Diagnostic](matched-lossless/manifest.json), [held-out prediction](matched-lossless/holdout/protocol.json), [held-out seed records](matched-lossless/holdout/seeds.csv), [vector figure](matched-lossless/heldout-order.pdf) | The follow-up reuses the first twelve seeds to separate absolute demand from scheduling, then tests the ordering prediction on twelve disjoint seeds. |
| Recovery baseline | [Reserved-slot records](recovery/reserved/runs.json.gz), [shared-pool records](recovery/tail-drop/runs.json.gz), [archived finite graph search](recovery/lockup-scan.jsonl) | Continuous-time Poisson inputs rounded to simulator ticks. Numerators and denominators for operation costs use the same half-open measurement window. |
| Tandem throughput and freeze traces | [Exact or numerical rates by case](theory/tandem.json), [uncapped freeze certificates](theory/uncapped-freezes.json), [verification manifest](theory/manifest.json) | Traces start empty, use the public simulator and record the physical origin of every stored qubit. The notes state the hypotheses of each rate or reachability result. |
| Earlier branch evidence | [Saturated check](prior/saturated-chain-theorem-02/check.json), [guarded check](prior/guarded-chain-01/check.json), [rule scan](prior/lockup-generalization-01/rule-scan.jsonl), [long-chain runs](prior/lockup-generalization-01/saturated-long-chains.json), [cutoff runs](prior/cutoff-outage-02/runs.json) | Copies of the existing local research records used by the chain and lockup notes. These historical files retain their original contents. |
| Prior diamond comparisons | [Q-CAST seed-level observations](prior/qcast/concurrent-main-01/observations.json), [physical accounting audit](prior/qcast/concurrent-main-01/independent-audit.json), [guarded diamond observations](prior/qcast/guarded-diamond-02/observations.json) | The earlier slotted experiments provide context for the choice of topology. The subset includes the seed summaries, plots and linked certificates used in the two diamond reports. Full JVM build caches and event logs can be regenerated with those reports' commands. |

## Verify or reproduce

Use Python 3.12 and the environment described in the [project README](../README.md). The first command checks source files and evidence using the standard library. For a Git checkout, initialize the pinned SeQUeNCe submodule before installing the local simulator. The portable ZIP already contains both submodule trees at the revisions recorded in the release manifest, so an extracted ZIP can skip the Git command below. The study's numerical evidence and the reference trace fingerprints can be inspected offline.

The release environment used NumPy 2.5.4, SciPy 1.18.1, NetworkX 3.7, Matplotlib 3.11.2 and SeQUeNCe 1.3.1 from the pinned checkout. The analysis reports paired seed intervals. On a different machine, floating-point estimates or figure metadata may vary slightly.

```text
python -m scripts.paper_evidence
git submodule update --init SeQUeNCe
python -m pip install -e ".[dev,simulation]"
python -m pip install --no-deps -e ./SeQUeNCe
python -m scripts.theory_evidence --output tmp/replayed-theory
python -m scripts.matched_srs --output tmp/replayed-matched --workers 8
python -m scripts.matched_srs_report tmp/replayed-matched
python -m scripts.matched_lossless_diagnostic --output tmp/replayed-order
python -m scripts.matched_order_holdout freeze --output tmp/replayed-order-holdout
python -m scripts.matched_order_holdout run --output tmp/replayed-order-holdout
python -m scripts.recovery_baseline --output tmp/replayed-reserved --workers 8 --gzip
python -m scripts.recovery_baseline --output tmp/replayed-shared --admissions tail_drop --arms none drop0 drop5 cutoff30 --workers 8 --gzip
python -m scripts.audit_recovery_results evidence/recovery
```

To rebuild the matched tables and figure directly from the released trajectories, run `python -m scripts.matched_srs_report evidence/matched`. The report verifies the design, input fingerprints and seed pairing. Figure error bars are pointwise intervals across paired seed blocks. Differences and their paired intervals are in the separate contrast table. Run `python -m scripts.plot_heldout_order` to draw the fixed-order triangle and the twelve held-out paired observations.

The SRS tests include three physical-register trace fingerprints from 288 slots of the original implementation. To replay the upstream implementation itself, set `SRS_UPSTREAM_SOURCE` to its pinned `main_cd.py` and run `python -m pytest tests/test_srs_protocol.py`. The live parity check disables consumption in both implementations. The queued-request study uses an externally supplied workload and identical per-pair FIFO service across arms. [Published protocol](https://arxiv.org/html/2307.01406v2) · [Pinned reference implementation](https://github.com/AlvaroGI/optimizing-cd-protocols/blob/3a68a05663a61dacefa59809646c55bcfaf2a493/main_cd.py)

The full release test run passed **817 tests** on Windows, including the native Q-CAST checks. To run those optional checks, set `QCAST_VALIDATION_DIR` to the completed native reference output and `QCAST_PILOT_BUILD` to the validated native bridge build before running `python -m pytest tests -q`. The default suite skips the native Q-CAST checks when those inputs are absent. [Reference build](../QCAST_Validation_Results.md) · [Native bridge](../scripts/qcast_pilot.py)

Each experiment manifest records its source files or inputs. The final tag identifies the complete runnable tree, including changes that were present in the working directory during long simulations. The release checksum list covers normalized source text and the actual compressed result files. Q-CAST belongs to an earlier slotted comparison and is outside the matched SRS experiment.

From the tagged Git checkout with its submodules initialized, run `python -m scripts.paper_evidence --archive dist/poqi-finite-memory-paper-v1.zip` to rebuild the portable release. Choose a new output path for a second copy.

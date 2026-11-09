# Higher-D scaling results

## Experiment

Extended the observation horizon from **1,000 to 10,000 iterations**, using the existing controlled comparison runner. Conditions: 25-node cycle and wrapped-grid overlay; 35 consumer pairs; `D=1,2,3`; released and corrected implementations; five paired repetitions; master seed **271**. Generation remains Poisson with batch mean 10 for every D, initial inventory is 20 pairs per physical edge, requests use the same blocking FIFO, and stopping is fixed with no discarded warm-up.

This uses the inventory-level simulator with unbounded storage. The 1,000- and 10,000-iteration observations are windows of the **same trajectories**, not extra independent repetitions. Graph/input seeds are unchanged from [Stat_Results.md](Stat_Results.md). This study varies D and observation length, not network size.

## Measurements

- **Completion rate:** completed requests divided by the observation horizon, in requests per iteration. Mean intervals are pointwise 95% Student-t intervals over the five runs.
- **Any completion:** fraction of runs with at least one completion by the horizon, with 95% Wilson intervals. Zero-success runs remain included.
- **First completion:** exact first completed-request iteration. If none completes by H, record `>H` (right-censored), not a completed event at H.
- **Restricted mean first-completion time:** average of `min(T_first, H)` across all runs. It includes censored runs at the observation boundary and is not the unconditional mean or the mean among successful runs only.

First service can use preloaded pairs, so this is not establishment latency from an empty network. With only five repetitions, confidence intervals remain pilot estimates. Approximate t intervals are not clipped to the metric's bounds. A zero-width sample interval for five identical observations does not establish zero population uncertainty; the completion-fraction interval provides separate information.

## Results

**All 60 trajectories finished.** The longer window reveals substantial D=2 service. D=3 remains sparse on the cycle and highly variable on the grid. These are finite-window averages, not established steady-state rates.

Each row has five repetitions. Arrows compare H=1,000 with H=10,000. Rates below are rescaled to **completions per 1,000 iterations**, measured over the full 10,000-iteration window.

| Topology | D | Implementation | Mean completions: 1,000 -> 10,000 | Long-window rate [95% CI] | Runs with any completion: 1,000 -> 10,000 |
| --- | ---: | --- | ---: | ---: | ---: |
| Cycle | 1 | Released | 604.0 -> 8,756.0 | 875.60 [777.36, 973.84] | 5/5 -> 5/5 |
| Cycle | 1 | Corrected | 723.8 -> 10,275.8 | 1,027.58 [934.38, 1,120.78] | 5/5 -> 5/5 |
| Cycle | 2 | Released | 1.0 -> 133.4 | 13.34 [9.20, 17.48] | 3/5 -> 5/5 |
| Cycle | 2 | Corrected | 2.0 -> 278.8 | 27.88 [22.70, 33.06] | 4/5 -> 5/5 |
| Cycle | 3 | Released | 0.2 -> 3.6 | 0.36 [-0.31, 1.03] | 1/5 -> 4/5 |
| Cycle | 3 | Corrected | 0.2 -> 3.6 | 0.36 [-0.31, 1.03] | 1/5 -> 4/5 |
| Grid | 1 | Released | 754.6 -> 10,094.2 | 1,009.42 [574.31, 1,444.53] | 5/5 -> 5/5 |
| Grid | 1 | Corrected | 858.2 -> 11,966.8 | 1,196.68 [756.13, 1,637.23] | 5/5 -> 5/5 |
| Grid | 2 | Released | 3.2 -> 412.6 | 41.26 [-7.03, 89.55] | 4/5 -> 5/5 |
| Grid | 2 | Corrected | 3.8 -> 716.6 | 71.66 [1.31, 142.01] | 4/5 -> 5/5 |
| Grid | 3 | Released | 1.8 -> 27.8 | 2.78 [-1.64, 7.20] | 2/5 -> 5/5 |
| Grid | 3 | Corrected | 0.4 -> 74.8 | 7.48 [-5.80, 20.76] | 2/5 -> 5/5 |

At H=10,000, the 95% Wilson intervals are **[37.6%, 96.4%] for 4/5** and **[56.6%, 100%] for 5/5**. Negative t-interval bounds reflect the approximate small-sample method, not negative observed rates.

First-completion iterations, ordered by repetition 0-4:

| Topology | D | Implementation | Individual first completions | Restricted mean [95% CI], H=10,000 |
| --- | ---: | --- | --- | ---: |
| Cycle | 2 | Released | 526, 2, 4728, 988, 1165 | 1,481.8 [-839.9, 3,803.5] |
| Cycle | 2 | Corrected | 802, 1, 3865, 934, 791 | 1,278.6 [-574.1, 3,131.3] |
| Cycle | 3 | Released | 4231, 33, **>10,000**, 3208, 4634 | 4,421.2 [-52.8, 8,895.2] |
| Cycle | 3 | Corrected | 4366, 33, **>10,000**, 4489, 4473 | 4,672.2 [279.0, 9,065.4] |
| Grid | 2 | Released | 993, 773, 71, 1627, 57 | 704.2 [-119.3, 1,527.7] |
| Grid | 2 | Corrected | 626, 762, 153, 1446, 100 | 617.4 [-60.1, 1,294.9] |
| Grid | 3 | Released | 2444, 2312, 723, 8107, 285 | 2,774.2 [-1,111.1, 6,659.5] |
| Grid | 3 | Corrected | 1434, 3592, 723, 6790, 344 | 2,576.6 [-738.3, 5,891.5] |

Cycle D=3 completion counts are `[3, 1, 0, 1, 13]` under both implementations. The zero-completion repetition remains right-censored, and its overhead remains undefined. Corrected code does not uniformly reduce time to first completion. Grid D=3 counts also vary widely: released `[6, 26, 89, 1, 17]`, corrected `[6, 97, 253, 1, 17]`. Sparse cases are results, not exclusions.

![Completion rates and run completion fractions with 95% intervals](results/scaling/report/scaling.png)

Outputs: [summaries](results/scaling/report/summary.csv), [individual observations](results/scaling/report/observations.csv), [seeds](results/scaling/report/seeds.csv), [full report](results/scaling/report/scaling.json), and raw-run manifests for [cycle](results/scaling/long-cycle/manifest.json) and [grid](results/scaling/long-grid/manifest.json). The numerical outputs also retain D=1 first-completion times and all shorter-window intervals.

## Code and validation

Production changes are limited to observing `first_completion_step` and recording elapsed run time. Swapping rules, generation, random streams, request handling and scheduling are unchanged. The [analysis script](scripts/scaling_analysis.py) reads the existing run/checkpoint outputs and retains sparse and censored cases.

- **207 example tests passed**, including the new first-completion tests and existing author-parity/replay tests.
- **30 reporting/verifier tests passed**: 20 scaling-analysis tests plus 10 existing saved-result checks. These cover Wilson boundaries, missing measurements, all-censored/mixed samples, shorter-window censoring, checkpoint validation and output protection.
- **All 60 saved runs validated**; the report contains 120 correlated observation windows. All 60 checkpoints at iteration 1,000 exactly reproduce the earlier pilot's counts, denominators, remaining inventory and queue heads. All ten input-tape prefixes match. First-completion observations agree with cumulative completion counts at all 600 checkpoints. The generated figure was visually checked.

## Reproduction

From the repository root, use new output directories:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'SeQUeNCe')
.\.venv\Scripts\python.exe -B -m example.path_oblivious_corrected.compare --steps 10000 --distillations 1 2 3 --replicates 5 --seed 271 --graph cycle --nodes 25 --checkpoint-interval 1000 --output results/scaling/long-cycle
.\.venv\Scripts\python.exe -B -m example.path_oblivious_corrected.compare --steps 10000 --distillations 1 2 3 --replicates 5 --seed 271 --graph wrap_grid_overlay --nodes 25 --checkpoint-interval 1000 --output results/scaling/long-grid
.\.venv\Scripts\python.exe -B scripts/scaling_analysis.py results/scaling/long-cycle results/scaling/long-grid --horizons 1000 10000 --output results/scaling/report
.\.venv\Scripts\python.exe -B -m pytest tests/test_scaling_analysis.py tests/test_implementation_results.py -q -o addopts= -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest SeQUeNCe/example/path_oblivious SeQUeNCe/example/path_oblivious_corrected -q -o addopts= -p no:cacheprovider
```

The [preprint](papers/2509.13993v1.pdf), p. 5, describes exponential overhead growth with D, whereas the [final HotNets paper](papers/hotnets25-final271.pdf), p. 6, describes almost-linear growth in its experiment. This controlled fixed-generation study does not identify either scaling law from sparse completions alone.

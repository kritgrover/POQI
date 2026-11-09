# Statistical results

Pilot analysis of existing runs; no new simulation sweep. All intervals below are **pointwise 95% Student-t confidence intervals across independent repetitions**, not standard deviations or intervals across events within a run.

## Method and seeds

For run values `x_i`, the interval is `mean(x) +/- t(0.975, n-1) * sample_sd(x) / sqrt(n)`. Paired comparisons apply the same calculation to the per-repetition differences. Undefined overheads remain undefined; missing/failed runs are rejected rather than silently excluded. A single run has no confidence interval.

| Experiment | Runs per condition | Horizon | Seeds and pairing |
| --- | ---: | --- | --- |
| Released versus corrected, cycle and grid overlay | 5 | 1,000 iterations | Master seed 271; graph/input seeds below; shared realized inputs within each pair |
| Memory-limited chain | 3 | 100 abstract time units | Seeds 271, 272, 273, matched across slot budgets |

The comparison uses 25 nodes and 35 consumer pairs. There are 60 saved comparison trajectories across two topologies, two implementations and `D=1,2,3`; these are **five repetitions per condition**, not 60 independent repetitions of one condition. The chain uses `D=1`, reserved admission, corrected balancing, no expiry, and six budgets (1, 2, 3, 4, 8, unlimited): 18 trajectories. Neither study discards warm-up.

Graph/input seed pairs for both comparison topologies:

| Repetition | Graph seed | Input seed |
| ---: | ---: | ---: |
| 0 | 1526892958 | 2907903773 |
| 1 | 2871921107 | 3582183111 |
| 2 | 3475781475 | 1860506842 |
| 3 | 1372226901 | 2024906070 |
| 4 | 2047583797 | 3913904582 |

The generated `statistics.json` also retains the input substream seeds. Only `results/memory/acceptance-chain-smoke` is analyzed; duplicate smoke folders do not add repetitions.

## Released versus corrected: D=1

Mean completions are **604.0 -> 723.8** on the cycle and **754.6 -> 858.2** on the grid overlay. The paired results are:

| Topology | Completion difference [95% CI] | Overhead difference [95% CI] |
| --- | ---: | ---: |
| Cycle | +119.8 [45.13, 194.47] | -0.5098 [-0.7527, -0.2669] |
| Grid overlay | +103.6 [18.90, 188.30] | -0.7354 [-1.2146, -0.2562] |

Differences are corrected minus released. Both overhead definitions coincide at `D=1`. These pilot intervals exclude zero for both metrics in both topologies; they do not establish performance outside the tested conditions. The percentage completion gains in `Issues_and_Fixes.md` are descriptive ratios of means, not percentage confidence intervals.

![Comparison means with 95% confidence intervals](results/statistics/pilot/comparison_d1.png)

## Memory-limited chain

| Slots per node | Mean throughput [95% CI] | Difference from unlimited [95% CI] |
| --- | ---: | ---: |
| 1, 2, 3 (each separately) | 0.000 [0.000, 0.000] | -0.897 [-0.973, -0.821] |
| 4 | 0.627 [0.490, 0.763] | -0.270 [-0.336, -0.204] |
| 8 | 0.827 [0.715, 0.939] | -0.070 [-0.113, -0.027] |
| Unlimited | 0.897 [0.821, 0.973] | Reference |

Throughput is completed requests per abstract time unit. Differences use matched seeds. Three zero observations produce a zero-width t interval; this alone does not prove that completion is impossible. The separate structural argument is needed for that claim.

![Memory throughput with 95% confidence intervals](results/statistics/pilot/memory_throughput.png)

## Limits, outputs and validation

These are short pilots with small sample sizes and approximate t intervals. Error bars describe run-to-run variation; they do not establish stationarity, remove initialization bias, or certify sufficient precision. No multiple-comparison adjustment is applied. `D=2,3` observations remain in the numerical output with low-completion/undefined-metric flags; they do not support a reliable overhead comparison.

Validation: **24 tests passed** (14 statistical-reporting tests and 10 saved-result-verifier tests). Checks cover a tabulated t critical value, paired estimates despite shuffled records, undefined observations, incomplete/duplicate runs, inconsistent seeds/data, and the actual error-bar values including the unlimited-memory reference. The report validated **60 comparison runs and 18 memory runs**; both figures were visually checked.

Outputs: [comparison summaries](results/statistics/pilot/comparison.csv), [memory summaries](results/statistics/pilot/memory.csv), [seeds](results/statistics/pilot/seeds.csv), and [full report](results/statistics/pilot/statistics.json). The [reporting script](scripts/statistical_analysis.py) writes these and the figures into a new output directory without modifying source results. Reproduce from the repository root:

```powershell
.\.venv\Scripts\python.exe -B scripts/statistical_analysis.py --output results/statistics/pilot
.\.venv\Scripts\python.exe -B -m pytest tests/test_statistical_analysis.py tests/test_implementation_results.py -q -o addopts= -p no:cacheprovider
```

Use a new output directory when rerunning the report.

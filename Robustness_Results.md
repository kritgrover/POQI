# Demand and horizon robustness

Pressure relaxation retains a throughput advantage over corrected balancing with **25% fewer slots** at demand 0.75 and 1.0 in this chain study. The advantage is conditional: queues can still grow, low-demand operation uses more swaps, and the two-slot no-expiry failure persists.

## Protocol

Test the existing corrected `balancing` and `pressure_relaxed` policies under lighter demand and longer observation. Simulator and policy code are unchanged.

- **600 trajectories:** three-node chain, independent Poisson generation at rate 1 per physical link; demand (0,2) at **0.5, 0.75 or 1.0**; capacities **2,3,4,8,unlimited**; no expiry or inherited cutoff **10**; two policies; ten fresh seeds **5271-5280** per condition.
- D=1, empty initial inventory, reserved admission, global FIFO. Identical generation/request inputs across capacities, policies and lifetime settings within each demand/seed. Different demand rates have different request streams.
- Each trajectory runs to **H=8,000** abstract time units. **Early:** [500,2,000). **Late:** [2,000,8,000). Window boundary events belong to the following window; backlog already present at the start is retained.
- Means and approximate **95% Student-t intervals** use ten independent seeds. Policy differences, late-minus-early differences, and cross-capacity differences are paired by seed. The two windows are correlated, not twenty independent runs. Intervals are pointwise and unclipped, with no multiple-comparison correction. Zero-width sample intervals do not establish zero population uncertainty; mixed stalled/active samples remain pilot estimates.
- Prespecified memory comparisons: **pressure c=3 versus balancing c=4** (25% fewer slots), and **pressure c=4 versus balancing c=8** (50% fewer slots). An interval crossing zero does not establish equivalence. No memory budget is fitted to these validation runs.

At demand 1, each link's generation rate equals the supply needed for endpoint service before losses; finite-memory loss leaves no spare supply. Lower loads test whether the observed queue growth persists with headroom. These finite windows cannot prove queue stability or identify a globally minimal memory budget.

## Measurements

Throughput is completions/window duration; blocking is rejected/offered physical generation; net backlog growth is `(queue_end - queue_start)/duration`; mean backlog is the time integral of queued requests divided by duration. Completed requests can have arrived before the window. Raw swap totals are compared only within equal windows; swaps/completion remains undefined when service is zero.

**Zero service** is a window observation. The separate **single-partner absorbing-stall** flag is a sufficient certificate at the window end: no expiry, pending endpoint demand, a full center, and all live pairs joining that center to only one endpoint. No generation, swap or completion can change that inventory. It deliberately does not classify every possible deadlock; in particular, balancing's two-partner threshold stall remains visible in its zero-service counts. Expiring inventories are not labelled permanently absorbing.

## Results

Late-window throughput, in completed requests per time unit. The difference is **three-slot pressure minus four-slot balancing**, paired by seed.

| Lifetime | Demand | Balancing, c=4 | Pressure, c=3 | Difference [95% CI] |
| --- | ---: | ---: | ---: | ---: |
| No expiry | 0.5 | 0.49872 | 0.49883 | +0.00012 [-0.00007, 0.00030] |
| No expiry | 0.75 | 0.66645 | 0.74000 | +0.07355 [0.06588, 0.08122] |
| No expiry | 1.0 | 0.66645 | 0.74983 | +0.08338 [0.08131, 0.08545] |
| Cutoff 10 | 0.5 | 0.49872 | 0.49882 | +0.00010 [-0.00010, 0.00030] |
| Cutoff 10 | 0.75 | 0.66612 | 0.74002 | +0.07390 [0.06618, 0.08162] |
| Cutoff 10 | 1.0 | 0.66612 | 0.74982 | +0.08370 [0.08167, 0.08573] |

**25% fewer slots:** higher measured throughput is supported at demand 0.75 and 1.0 under both lifetime settings. At demand 0.5 the rate difference is unresolved. Without expiry, three-slot pressure has a smaller mean queue, **0.74 versus 1.32**, but more swaps/completion, **1.324 versus 1.000**. With cutoff 10, those comparisons are **0.76 versus 1.40** and **1.350 versus 1.035**. This is a memory/queue/operation-cost tradeoff, not an equivalence guarantee.

**50% fewer slots:** four-slot pressure versus eight-slot balancing loses throughput at demand 1.0: paired differences are **-0.05627 [-0.05831,-0.05423]** without expiry and **-0.05555 [-0.05777,-0.05333]** with cutoff 10. At lighter demand the rate differences are unresolved, while pressure has a larger queue and higher swap cost. For example, at demand 0.75 without expiry, mean queues are **9.83 versus 2.63**. The larger memory saving does not preserve every measured service property.

**Longer observation:** all 60 late-minus-early throughput intervals contain zero. This does not establish queue stability. For three-slot pressure at demand 0.75 without expiry, mean queue rises from **24.46 to 55.45**; late net growth is **0.00572 [0.00008,0.01135]** requests/time unit. With cutoff 10, late mean queue is **55.60** and growth **0.00570 [0.00005,0.01135]**. At demand 1.0, three-slot pressure queues grow by about **0.248** requests/time unit under either lifetime setting.

At demand 0.75, four-slot pressure has much less backlog: without expiry its late mean queue is **9.83**, and net growth **-0.00085 [-0.00202,0.00032]**. This is finite-window evidence of better load handling, not a proof of a stationary queue.

### Two-slot failure and expiry

Pressure-policy zero-service counts below are identical in the early and late windows. Each no-expiry zero-service run also has the certified absorbing state; no new certificate appears only in the late window.

| Demand | No expiry: zero-service / absorbing runs | Cutoff 10: zero-service runs |
| --- | ---: | ---: |
| 0.5 | 10/10 | 0/10 |
| 0.75 | 9/10 | 0/10 |
| 1.0 | 6/10 | 0/10 |

Longer runs do not release those permanently trapped inventories. With cutoff 10, two-slot pressure serves requests in every measured window; at demand 0.5 its late throughput is **0.49872**, with mean queue **4.19**. Expiry releases the known trap in this model. These sample counts do not certify population stall probabilities. No pressure run at three or more tested slots has a zero-service window. Balancing at two or three slots remains structurally unable to swap.

**Blocking and storage:** at demand 0.5 without expiry, generation blocking is about **41.88%** for three-slot pressure versus **49.99%** for four-slot balancing, despite both serving about 0.499 requests/time unit. Generation rejection includes unused supply; it is not request loss. In the unlimited no-expiry controls at that demand, mean stored inventory grows from **1,526.4 pairs at time 2,000 to 6,021.5 at time 8,000**, despite a short request queue. These results do not establish stationary holding times for memory sizing.

![Late-window throughput, blocking and backlog growth with 95% intervals](results/memory/robustness-main/report/late.png)

The dotted throughput line marks nominal demand. Additional figures: [early window](results/memory/robustness-main/report/early.png), [paired horizon changes](results/memory/robustness-main/report/horizon_changes.png). Numerical outputs: [full report](results/memory/robustness-main/report/robustness.json), [all summaries](results/memory/robustness-main/report/summary.csv), [policy differences](results/memory/robustness-main/report/paired.csv), [horizon differences](results/memory/robustness-main/report/horizon_changes.csv), [memory comparisons](results/memory/robustness-main/report/memory_comparisons.csv), [individual windows](results/memory/robustness-main/report/observations.csv), [manifest](results/memory/robustness-main/manifest.json), and [independent audit](results/memory/robustness-main/independent_audit.json).

## Saturated-service check

A small continuous-time calculation explains the relevant load thresholds. With **no expiry and an always-pending endpoint queue**, record the direct-link counts `(l,r)` after settling and service. The reachable recurrent states below have equal stationary probabilities under unit-rate generation; rejected arrivals are self-transitions. Summing service-producing transition rates gives:

| Policy | Recurrent states | Saturated service rate |
| --- | --- | ---: |
| Pressure, c=3 | `(0,0),(1,0),(2,0),(0,1)` | 3/4 = 0.7500 |
| Balancing, c=4 | `(1,1),(2,1),(1,2)` | 2/3 = 0.6667 |
| Pressure, c=4 | `(1,0),(2,0),(1,1),(0,1),(0,2)` | 4/5 = 0.8000 |

In these reachable states, generating 02 leaves no qualifying backward swap, and FIFO consumes it. All **24 one-arrival transitions** were checked against the actual simulator, and the uniform probabilities satisfy each generator's balance equations ([calculation](results/memory/robustness-main/saturation_check.json)). These are saturated continuous-time benchmarks; the experiments use offered Poisson requests and rounded timeline ticks. Demand 0.75 provides no strict service margin for pressure at three slots. Positive finite-window queue growth there does not by itself establish an asymptotic drift or a different service limit.

## Reproduction

The full root suite passed **400 tests**, including **21** new window-observer tests and **18** new reporting tests. Coverage includes carried demand, exact boundary events, expiry recovery, absorbing-state certification, independent paired-interval calculations, undefined ratios and corrupted/missing records. Separate short serial and parallel smoke experiments each ran 120 trajectories.

All **600 main runs** passed full event replay; **60 unlimited-memory policy pairs** have identical event logs and window metrics. The independent audit rederived **10,800 measurements and 3,600 flags**, verified all raw-artifact hashes, and checked all **120 group summaries, 60 policy contrasts, 60 horizon contrasts and 24 cross-capacity contrasts**. The primary table matches the final report, and the figures were visually checked. Source hashes confirm that the experiment code stayed fixed during the main run.

New analysis: [runner and reporting](scripts/memory_robustness_analysis.py), [disjoint-window observer](scripts/robustness_observations.py), and their tests. From the repository root, use fresh output directories:

```powershell
.\.venv\Scripts\python.exe -B scripts/memory_robustness_analysis.py --output results/memory/robustness-main --workers 3
.\.venv\Scripts\python.exe -B scripts/memory_robustness_analysis.py --from-runs results/memory/robustness-main --output results/memory/robustness-reanalysis --workers 3
.\.venv\Scripts\python.exe -B -m pytest -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/robustness-tests
```

The manifest records seeds, source hashes, protocol and software revisions. Parallel workers run separate trajectories; early/late measurements come from one trajectory per seed/condition. Compact gzip logs use compression level 1. Generated outputs remain under the ignored `results/` directory.

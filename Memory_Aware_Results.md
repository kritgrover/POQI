# Memory-aware swapping

## Structural stall and change

The [corrected sequence implementation](SeQUeNCe/example/path_oblivious_corrected/model.py) and the root simulator's `balancing` policy both require

`o + 1 <= min(l - D, r - D)`,

where `l=C_x(y)`, `r=C_x(y')`, and `o=C_y(y')`. Integer counts therefore require at least `D+o+1` pairs on **each** input, occupying at least `2(D+o+1)` slots at pivot x. With D=1 and o=0, fewer than four pivot slots makes every such swap impossible, irrespective of queued demand. Four is necessary, not sufficient: reserved quotas and the distribution across partners can still prevent it. This argument concerns swaps; direct-link requests can still complete.

Added the optional **`pressure_relaxed`** policy. It accepts the original predicate, or, under memory pressure, the one-count relaxation

`o <= min(l - D, r - D)`.

Pressure means either the finite pivot is full, or one of the actual oldest input qubits to be consumed occupies a saturated **positive** generation-neighbor reservation. An unrelated full reservation does not qualify. Pressure is recomputed after each swap. This matters because point 4 found reservation blocking below total capacity.

Physical feasibility still requires D pairs on both inputs. The relaxed bound is `2(D+o)` pivot slots: two when D=1 and o=0. Unlimited memory never triggers relaxation. Candidate priority, oldest-input selection, inherited expiry, reservations and FIFO service timing are unchanged. There are no evictions or demand weights. Each swap decreases total live pairs by `2D-1`, so repeated swaps terminate.

Deterministic trace: request (0,2), generate one (0,1) pair, then one (1,2) pair. At uniform capacities 1/2/3, corrected balancing completes **0/0/0** requests; pressure relaxation completes **0/1/1**. Tests also check D=1,2,3 boundaries, nonempty outputs, unrelated/mixed-origin quotas, expiry and pressure recomputation.

**A remaining deadlock:** at c=2 without expiry, generate 01,12 to create 02 before demand arrives; generate another 12, allowing a backward swap at node 2 to recreate 01. Another 01 generation leaves two 01 pairs, the center full, and no pivot with two partners. Demand 02 cannot drain this state, and every generation needs the full center. Relaxation removes the four-slot threshold but does not guarantee progress; this counterexample is also a deterministic regression test.

A [subsequent theorem](Saturated_Chain_Theorem.md#offered-demand-at-two-slots) establishes when this lockup occurs eventually in the continuous-time two-slot chain from empty. At unit generation per link and Poisson demand at or below 2/3, the probability is one. Above 2/3, a busy period can keep consuming every output before it is swapped backward. At offered rate one the exact probability of eventually locking is approximately 0.4853.

## Experiment

- **540 trajectories:** three scenarios, six capacities, three policies, ten seeds **4271-4280** per condition. H=2,000 abstract time units; rate and time-average queue measurements use [500,2,000). Final backlog includes all unfinished requests.
- **Chain:** three nodes, generation rate 1 per link, endpoint demand rate 1; separate no-expiry and inherited-cutoff-10 scenarios. Slots/node: **2,3,4,8,16,unlimited**.
- **Star:** center 0, leaves 1/2/3, generation rate 1 per spoke, cutoff 10; demands (1,2)=0.6, (1,3)=0.3, (2,3)=0.1. Slots/node: **3,4,6,8,16,unlimited**.
- D=1, empty initial inventory, reserved admission. Compare corrected balancing, pressure relaxation and the existing physically feasible swap policy. The last is a diagnostic, not a throughput upper bound.
- Identical generation/request streams across policies and budgets for each scenario/seed. Report pointwise **95% Student-t intervals across ten runs**, with differences paired by seed. No zero-service runs are discarded. These are finite-window pilot results, not a stability or optimality claim.

Swaps/completion is a windowed activity ratio, not the paper's normalized overhead. A zero-completion denominator remains undefined. Per-demand throughput divided by nominal demand is a service-rate ratio, not a completion probability.

## Results

Throughput is completed requests per abstract time unit. Differences below are pressure relaxation minus corrected balancing, paired by seed.

| Scenario | Slots/node | Balancing | Pressure | Difference [95% CI] |
| --- | ---: | ---: | ---: | ---: |
| Chain, no expiry | 2 | 0 | 0.3351 | +0.3351 [0.0823, 0.5879] |
| Chain, no expiry | 3 | 0 | 0.7522 | +0.7522 [0.7380, 0.7664] |
| Chain, no expiry | 4 | 0.6681 | 0.8033 | +0.1351 [0.1286, 0.1417] |
| Chain, no expiry | 8 | 0.8588 | 0.8911 | +0.0323 [0.0305, 0.0341] |
| Chain, no expiry | 16 | 0.9394 | 0.9473 | +0.0079 [0.0069, 0.0089] |
| Chain, cutoff 10 | 2 | 0 | 0.6681 | +0.6681 [0.6564, 0.6798] |
| Chain, cutoff 10 | 3 | 0 | 0.7521 | +0.7521 [0.7379, 0.7663] |
| Chain, cutoff 10 | 4 | 0.6679 | 0.8031 | +0.1352 [0.1286, 0.1418] |
| Chain, cutoff 10 | 8 | 0.8581 | 0.8905 | +0.0324 [0.0304, 0.0344] |
| Chain, cutoff 10 | 16 | 0.9347 | 0.9419 | +0.0072 [0.0060, 0.0084] |
| Star, cutoff 10 | 3 | 0 | 0.7997 | +0.7997 [0.7814, 0.8180] |
| Star, cutoff 10 | 4 | 0 | 0.8832 | +0.8832 [0.8632, 0.9032] |
| Star, cutoff 10 | 6 | 0.7755 | 0.9627 | +0.1872 [0.1709, 0.2035] |
| Star, cutoff 10 | 8 | 0.9236 | 0.9813 | +0.0577 [0.0427, 0.0726] |
| Star, cutoff 10 | 16 | 0.9800 | 0.9824 | +0.0024 [-0.0038, 0.0086] |

**The two-slot no-expiry failure remains:** five of ten pressure runs have zero service throughout the measurement window, all trapped in the single-partner state described above. Seeds are **4272,4274,4275,4276,4277**. Three never complete a request; two complete one before stalling. The wide interval mixes stalled and active runs. With cutoff 10, every two-slot pressure run serves requests in the measurement window.

At four slots, the star's center reservations are 2/1/1: no pair of partners can each supply the two inputs required by balancing. Pressure relaxation removes that additional reservation-induced stall.

| Condition | Generation blocking, balancing -> pressure | Mean backlog, balancing -> pressure | Swaps/completion, balancing -> pressure |
| --- | ---: | ---: | ---: |
| Cutoff chain, c=4 | 33.246% -> 19.765% | 409.40 -> 242.88 | 1.000 -> 1.000 |
| Cutoff star, c=6 | 38.740% -> 23.110% | 278.20 -> 57.86 | 1.179 -> 1.239 |

In the cutoff chain at c=4, all **12,047** relaxed swaps across the ten measurement windows occur below total pivot capacity and are enabled by saturated input reservations. In the star at c=6, mean per-demand throughput improves from **0.4616/0.2342/0.0797** to **0.5785/0.2863/0.0978**, in demand order (1,2)/(1,3)/(2,3); each demand receives service in every pressure run. A higher swaps/completion ratio accompanies that improvement.

The physical-swap diagnostic illustrates why generation blocking alone is insufficient: at cutoff-chain c=4 it lowers blocking to **15.28%**, but throughput falls to **0.4632**, below balancing's 0.6679.

**Limits:** all finite-chain pressure conditions still have positive mean backlog growth. Star c=16 has no resolved throughput gain: its paired interval includes zero, although generation blocking falls from 10.404% to 5.650%. The rare pair's mean throughput changes slightly downward, 0.09847 to 0.09827; this is not evidence of universal per-demand improvement.

Unlimited pressure and balancing trajectories match exactly for **all 30 seed/scenario pairs**. Their mean throughputs are **0.9877/0.9511/0.9033** for the no-expiry chain/cutoff chain/cutoff star. Unlimited memory is an equivalence control, not a throughput ceiling: the star performs better at some finite budgets under these policies. The results support a memory-aware extension of corrected balancing while leaving deadlock prevention, demand awareness and queue stability open.

![Throughput, blocking and backlog with 95% intervals](results/memory/policy-point5/report/policy.png)

Outputs: [full report](results/memory/policy-point5/report/policy.json), [summary and intervals](results/memory/policy-point5/report/summary.csv), [paired differences](results/memory/policy-point5/report/paired.csv), [per-demand results](results/memory/policy-point5/report/per_pair.csv), [individual observations](results/memory/policy-point5/report/observations.csv), [independent audit](results/memory/policy-point5/independent_audit.json), and [manifest](results/memory/policy-point5/manifest.json).

## Validation and reproduction

The full root suite passed **361 tests**, including 28 new policy tests and 25 reporting tests. The reporting tests include a separate 108-trajectory short smoke experiment, warm-up queue integration, FIFO checks, undefined ratios, paired statistics and corrupted/missing records.

All **540 saved runs** pass replay checks for physical-slot accounting, capacity, FIFO service, executed-swap eligibility, relaxation counters and matched inputs. An independent raw-event audit rederives **2,700 scalar measurements**, checks their group means and paired intervals, and confirms the 30 identical unlimited controls and five absorbing states. Every throughput-table entry matches the final report; the figure was visually checked.

Implementation: [policy](src/poqi/simulation/sequence_adapter.py), [configuration](src/poqi/config.py), [experiment and event-log analysis](scripts/memory_policy_analysis.py). Set `simulation.swap_policy` to `pressure_relaxed` to opt in; the default remains `balancing`.

From the repository root, use fresh output directories:

```powershell
.\.venv\Scripts\python.exe -B scripts/memory_policy_analysis.py --output results/memory/policy-point5
.\.venv\Scripts\python.exe -B scripts/memory_policy_analysis.py --from-runs results/memory/policy-point5 --output results/memory/policy-point5-reanalysis
.\.venv\Scripts\python.exe -B -m pytest -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/point5-tests
```

Raw logs, numerical reports and figures remain under the ignored `results/` directory. The manifest records seeds, settings and source hashes.

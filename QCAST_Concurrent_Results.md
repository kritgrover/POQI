# Q-CAST comparison with matched concurrent service

## Finding

Allowing every system to serve independent pending demand pairs removes the
earlier global-FIFO restriction. In this targeted diamond experiment, concurrent
Q-CAST has higher measured total service than every POQI arm at two qubits/node
and at four qubits with link failures. At four qubits with perfect links, its
throughput difference from persistent pressure relaxation is unresolved.
This is not per-demand dominance: at two qubits with lossy links, Q-CAST leaves
pair 12 without any measured-window service in all ten runs.

These results compare complete systems under the
[fixed follow-up protocol](QCAST_Concurrent_Protocol.md), including their storage,
allocation and information differences. They do not replace the earlier
[chain findings](QCAST_Pilot_Results.md), establish a universal winner, or change
the root continuous-time simulator. Original Q-CAST routing remains in a
reset-at-slot-boundary wrapper; persistent POQI remains explicitly labelled
as an opportunity-clock adaptation. No persistent Q-CAST was implemented.

## Executed design

Completed November 20, 2026 (America/Toronto): **560 trajectories / 224,000 slots**,
four physical conditions, seven algorithm/storage systems, both FIFO and
concurrent-per-pair service, and ten fresh paired seeds **7271-7280**. H=400;
measure useful completions at **(100,400]**, costs in slots starting 100..399,
and backlog from true arrivals. All runs start empty. No grid expansion or
seed selection followed inspection of these results.

- Diamond edges 01,02,13,23; memory **2 or 4 qubits/node**; **p=1 or .5**;
  **D=1, q=1, Delta=1**; two named channel opportunities/edge/slot.
- Poisson unit-request rates 03=.5, 01=.25, 12=.15; total nominal load .9.
- Q-CAST with recovery k=1; POQI balancing/pressure relaxation with slot reset,
  persistence without expiry, or persistence with inherited cutoff 10.
- Same physical potential outcomes keyed by seed/topology/slot/edge/lane,
  independent of system and service rule. Failed selected attempts reserve
  both endpoint qubits for the full slot. Different choices need not produce
  the same realized successful generation.
- Concurrent service preserves oldest-first order within each unordered pair,
  bypasses unavailable unrelated requests and consumes each physical pair once.
  Both POQI service phases use this rule; there are no extra swaps between
  consumptions. Changing service can change later pending sets and allocation.

The unit-request queues are workload wrappers, not the original paper's exact
demand model. Q-CAST retains route-aware allocation; POQI retains frozen fixed
neighbor reservations, swap predicates and ordering. Shared physical budgets
do not erase these algorithmic differences.

## Useful service and waiting

Mean window completions per time unit; every entry retains all ten seeds.
B = balancing, P = pressure relaxation. Persistent and cutoff rows use the
opportunity-clock wrapper. The report contains all pointwise intervals.

| System, concurrent service | M2, p=1 | M2, p=.5 | M4, p=1 | M4, p=.5 |
| --- | ---: | ---: | ---: | ---: |
| Q-CAST slot | .9020 | .5810 | .9020 | .9050 |
| POQI slot B | .2387 | .2397 | .3860 | .4327 |
| POQI slot P | .1473 | .4550 | .7557 | .3550 |
| POQI persistent B | .2380 | .2387 | .3840 | .4900 |
| POQI persistent P | .1460 | **0** | .8983 | .5913 |
| POQI cutoff-10 B | .2380 | .2387 | .3893 | .5437 |
| POQI cutoff-10 P | .2450 | .3017 | .8980 | .5897 |

At **M4, p=.5**, Q-CAST exceeds persistent pressure by **.31367
[.27990,.34743]** completions/time, approximately 53% of the latter's mean.
At **M4, p=1**, the same paired difference is **.00367
[-.01066,.01799]**: unresolved, not evidence of equivalence. Q-CAST still has
lower mean backlog there: 1.704 versus 5.554; paired difference **-3.8503
[-5.9562,-1.7444]**.

| M4, p=.5, concurrent service | Q-CAST slot | Persistent pressure |
| --- | ---: | ---: |
| Throughput [95% CI] | .9050 [.8582,.9518] | .5913 [.5672,.6154] |
| Mean backlog | 2.93 | 82.93 |
| Final backlog | 1.6 | 130.4 |
| Completed-request mean latency | 3.23 | 61.17 |
| Full-cohort restricted mean wait | 3.21 | 73.59 |
| Attempts/completion | 6.87 | 9.37 |
| Swaps/completion | .96 | 3.63 |
| Mean allocated qubits, network total | 12.40 | 14.76 |

Restricted wait includes unfinished requests censored at H. Latency and cost
ratios are conditional on their defined observations; zero-service ratios
remain undefined. Cheaper ratios for some balancing arms accompany poorer
coverage and a different served-demand mix, so they do not establish general
efficiency superiority. Qubit cost includes failed-trial reservations and
stored endpoints; it is not just successful generation.

## Demand coverage, service control and failures

At **M2, p=.5**, Q-CAST's .5810 total exceeds reset pressure's .4550 by
**.1260 [.08718,.16482]**, but their per-pair rates differ materially:

| Demand pair (nominal rate) | Q-CAST slot | POQI slot pressure |
| --- | ---: | ---: |
| 03 (.50) | .34167 | .11600 |
| 01 (.25) | .23933 | .19333 |
| 12 (.15) | **0** | .14567 |

Q-CAST pair 12 has zero window service in **10/10 runs**, with mean final
backlog **58.3** and restricted wait **202.21**. Reset pressure serves all
three classes in every run. This is a demonstrated finite-window coverage
failure, not a proof of indefinite starvation. At M4, p=.5, Q-CAST serves all
classes, at rates **.51700/.23933/.14867**. Finite-window throughput divided
by nominal load can exceed one; it is distinct from the full-cohort completed
fraction. Both quantities are reported separately in the derived per-pair CSV.

The matched service control retains **193/280 zero-service FIFO runs** versus
**10/280 concurrent runs**. Q-CAST has zero measured-window service in all
40 FIFO runs and none of its 40 concurrent runs. Concurrent-minus-FIFO service
intervals exclude zero on the positive side in **27/28 system-condition cells**.
This confirms that the earlier FIFO result was a service-interface interaction;
the rerun applies the same service rule to POQI as well.

The unchanged cell is **M2, p=.5, persistent pressure without expiry**:
all ten concurrent runs still have zero late service and mean final backlog
363.8. These trajectories are retained. The existing chain absorbing-state
regression also remains tested; its certificate does not prove that a diamond
state is absorbing. Pressure is not uniformly beneficial: at M4, p=.5,
pressure-minus-balancing throughput is **-.07767 [-.09053,-.06480]** with
reset, versus **+.10133 [.06781,.13485]** with persistence.

## Validation and provenance

The author source remains exactly
**`0a0251dd5f38eb1669ff6abe18ab83436ddbba18`**, with paper/version and
accounting qualifications in [reference validation](QCAST_Validation_Results.md).
Root starting revision: **`f359d2c7546df937097f2b5acf2cbf5be73e56f3`**.
New sources are uncommitted; the manifest records their exact hashes, protocol,
frozen root helpers, native source/build, dependency jars and compiled classes.
The portable Java/Maven build from `pilot-smoke-01` was reused and checked.

The full root suite passed **696 tests, no skips, in 33.21 seconds**: 556 prior
tests plus 61 new runner and 79 new audit tests. Tests include exact FIFO replay
of saved results across all seven systems, exact replay of the earlier native
concurrent diagnostic, single-pair equivalence between service modes, cached
start and settled end consumption, expiry, boundary arrivals, per-pair censored
waiting, and deliberate physical/service/report/provenance corruptions.
A separate 56-trajectory, 12-slot smoke run passed before the main run.

Independent replay **passed all 560 trajectories, 224,000 slots and 61,664
completions**, checking 17,360 observation fields, 1,680 per-pair records,
56 groups and 76 paired contrasts. All 203 zero-service trajectories remain
in the summaries. All 560 raw hashes and 174 native runtime hashes match;
there were no failed software trajectories in the main run.

Full-horizon pair conservation has zero residual in every trajectory:
**563,662 successful elementary generations = 234,278 swap reductions +
61,664 useful consumptions + 14,796 expiry losses + 251,711 reset losses +
1,213 final stored pairs**. These are totals across all runs and the full
horizon, not late-window rates. Stored inventory is a boundary stock, never
summed across slots as newly produced ebits.

The checker reconstructs physical admission, reservations,
swaps, endpoint-valid native pairs, service order, consumption, queue areas,
censoring, per-pair observations and all prescribed contrasts. It does not
independently reimplement the author's path-ranking algorithm. The native
delivery guard remains consequential: **3,379 measured slots** flag raw-author
versus physical-accounting discrepancies (3,000 FIFO, 379 concurrent).
Useful service uses verified physical pairs, leaving P2/P4 unchanged.

## Reproduction and limits

From `E:\POQI`, use new output directories for reruns:

```powershell
.\.venv\Scripts\python.exe -B scripts/qcast_concurrent.py --output results/qcast/concurrent-main-01 --build results/qcast/pilot-smoke-01/build --horizon 400 --warmup 100 --replicates 10 --seed 7271
.\.venv\Scripts\python.exe -B scripts/qcast_concurrent_audit.py results/qcast/concurrent-main-01
.\.venv\Scripts\python.exe -B scripts/qcast_concurrent_plot.py results/qcast/concurrent-main-01
.\.venv\Scripts\python.exe -B results/qcast/concurrent-main-01/conservation_ledger.py
$env:QCAST_PILOT_BUILD='E:/POQI/results/qcast/pilot-smoke-01/build'
$env:QCAST_VALIDATION_DIR='E:/POQI/results/qcast/validation-03'
.\.venv\Scripts\python.exe -B -m pytest tests -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/qcast-concurrent-full-tests-01
```

- [Manifest and source hashes](results/qcast/concurrent-main-01/manifest.json),
  [all group/paired statistics](results/qcast/concurrent-main-01/report.json),
  [seed/per-pair observations](results/qcast/concurrent-main-01/observations.json).
- [Independent audit](results/qcast/concurrent-main-01/independent-audit.json),
  [full-horizon conservation ledger](results/qcast/concurrent-main-01/conservation-ledger.json),
  [full test log](results/qcast/concurrent-full-tests-01.log).
- [Summary CSV](results/qcast/concurrent-main-01/figures/summary.csv),
  [per-pair CSV with distinct rate/fraction metrics](results/qcast/concurrent-main-01/figures/per_pair_summary.csv),
  [figure/export provenance](results/qcast/concurrent-main-01/figures/figure-manifest.json).

![Concurrent useful throughput, all systems and physical conditions](results/qcast/concurrent-main-01/figures/concurrent_throughput.png)

The separate [per-pair figure](results/qcast/concurrent-main-01/figures/concurrent_per_pair_throughput.png)
shows coverage failures hidden by aggregate service. Both figures were visually
checked, and all 336 derived rate/fraction rows were checked against seed-level
observations. [Aggregate PDF](results/qcast/concurrent-main-01/figures/concurrent_throughput.pdf);
[per-pair PDF](results/qcast/concurrent-main-01/figures/concurrent_per_pair_throughput.pdf).

Intervals are pointwise 95% Student-t intervals across seeds; contrasts use
paired-seed differences, with no multiplicity correction. The targeted
topology/grid followed the earlier diagnostic; fresh
seeds do not make it a general benchmark. H=400, D=1 and q=1 do not establish
queue stability, stochastic-swap behavior, large-network performance or classical
communication cost. The next comparison should map demand coverage and storage
tradeoffs under varied load/topology, retaining these failed cases. Shared
slotted and persistent-opportunity experiments should remain separately labelled;
the original continuous-time memory results keep their own model.

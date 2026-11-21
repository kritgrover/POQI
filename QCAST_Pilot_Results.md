# Matched-opportunity Q-CAST pilot

## Finding and scope

There is no universal winner in this first matched pilot. Persistent pressure
relaxation improves service and uses fewer measured trials per completion than
the Q-CAST slot wrapper on the three-slot lossy chain. At four slots their service difference is
unresolved. The diamond exposes a strong incompatibility between Q-CAST's
concurrent allocation and global FIFO consumption; a separate service-rule
diagnostic removes that failure. It would be misleading to call the diamond
zeros evidence that original Q-CAST cannot route those demands.

The [protocol](QCAST_Pilot_Protocol.md) was fixed before inspecting performance.
This is a comparison of **complete, explicitly labelled systems**, not a pure
swap-rule experiment or a persistent Q-CAST implementation. The root
continuous-time simulator, `balancing`, `pressure_relaxed`, reservations and
inventory code are unchanged. POQI arms reuse their actual settling, pressure
and swap methods in a new opportunity-clock wrapper. Q-CAST uses the unmodified
author routing code at **`0a0251dd5f38eb1669ff6abe18ab83436ddbba18`**; source
and paper/version qualifications remain in [reference validation](QCAST_Validation_Results.md).

## Completed experiment

- **700 trajectories / 280,000 slots:** ten conditions, seven arms, ten paired
  seeds **6271-6280**, H=400, empty initial state. Service is measured at
  timestamps **(100,400]**; costs use slots starting 100..399; backlog includes
  arrivals before they become visible to a decision.
- **Physical budget:** Delta=1, two named channels per physical edge, at most
  one trial/channel/slot, equal node qubit limits, **D=1**, **q=1**, and
  **p=1 or .5**. Failed trials occupy their reserved endpoint qubits for the
  full slot. All edges have unit length; Q-CAST uses alpha=-log(p), recovery
  enabled, k=1. There are no hidden retries or unequal successful-arrival feeds.
- **Chain:** 0-1-2, memory 2/3/4 per node, request rate 02=.75.
  **Diamond:** edges 01,02,13,23, memory 2/4, request rates
  03=.5, 01=.25, 12=.15.
- **Seven arms:** QCAST-Slot-FIFO; balancing/pressure with slot reset;
  balancing/pressure with persistent inventory and no expiry; and
  balancing/pressure with persistence and inherited cutoff 10.
- Identical continuous Poisson requests and potential link outcomes are
  shared by topology/seed. Hash keys identify physical edge/channel/slot,
  independently of policy decisions and capacity. Allocation precedes outcome
  revelation. Different selected opportunities can produce different successes.
  POQI channel ordering is separately keyed; its neighbor quotas remain fixed.

Arrivals become visible at the next integer epoch. End-slot operations are
expiry, successful-generation batch, swapping, eligible FIFO consumption,
and optional reset. Persistent arms can consume already-formed cached pairs
at the next start, before reserving trials; they do not run an extra start
swap round. Last-slot arrivals remain in final backlog. These timing rules
differ from the earlier Poisson-success continuous-time experiments.

Uncertainty uses pointwise **95% Student-t intervals across ten seeds** and
paired seed differences, not slots as replicates. No multiplicity correction,
stability claim or equivalence test is made. Finite-window realized demand and
carried backlog can make measured service differ from nominal offered rates.
Allocated-qubit means below are network totals, including in-flight reservations.

## Chain results

Mean useful completions per time unit at p=.5; every entry includes all ten
runs. B = balancing; P = pressure relaxation. Full group intervals and all
p=1 results are in the linked report and figure.

| Slots/node | Q-CAST slot/FIFO | Slot B | Slot P | Persistent B | Persistent P | Cutoff-10 B | Cutoff-10 P |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | .2600 | 0 | .2587 | 0 | .2280 | 0 | .3757 |
| 3 | .3830 | 0 | .3847 | 0 | .4840 | 0 | .4837 |
| 4 | .6367 | .0647 | .3263 | .3757 | .6240 | .3690 | .6240 |

**Three slots:** persistent pressure exceeds Q-CAST by **.1010
[.08036,.12164]** completions/time, about 26% of the Q-CAST mean. Reset pressure
instead achieves .3847, illustrating why storage must be part of the label.

| Three-slot chain, p=.5 | Q-CAST slot/FIFO | Persistent pressure |
| --- | ---: | ---: |
| Throughput [95% CI] | .3830 [.3605,.4055] | .4840 [.4694,.4986] |
| Mean backlog | 98.33 | 70.96 |
| Mean latency among measured completions | 121.93 | 88.38 |
| Mean age of unfinished requests at H | 102.16 | 75.20 |
| Trials/completion | 7.88 | 3.98 |
| Swaps/completion | 1.00 | 1.00 |
| Mean allocated qubits, including failed trials | 6.00 | 6.00 |

**Four slots:** Q-CAST minus persistent pressure is **+.01267
[-.00620,.03154]**, so the service difference is unresolved, not equivalent.
Mean backlog is 40.62 versus 38.57; trials/completion are 6.29 versus 3.99.
Mean allocated qubits are 7.99 versus 8.01. Persistent inventory avoids
repeating some successful halves of failed end-to-end attempts.

**Two slots:** the no-expiry pressure arm retains **4/10 absorbing,
zero-service runs**. Its .2280 mean mixes active and stalled trajectories.
Cutoff 10 serves in every run and exceeds Q-CAST by **.11567
[.09150,.13983]**. Balancing at two and three slots remains unable to swap.
At p=1, Q-CAST and pressure chain rates are all approximately .793-.794;
the measured Q-CAST/persistent-pressure throughput differences are unresolved.
Substantial p=.5 backlogs remain; these runs do not establish stability.

Ratios are per-run window activity ratios. Where service is zero they remain
undefined, and summaries report the number of defined runs. In particular,
the two-slot no-expiry pressure cost/latency summaries use six defined runs;
its throughput, backlog and stall summaries retain all ten. Completed-only
latency must be read with unfinished ages and restricted waiting time.

## Diamond failure and separate service diagnostic

QCAST-Slot-FIFO has **zero late-window service in all 40 diamond runs**.
Allocation still creates valid pairs, but can repeatedly favor pending pairs
other than the global queue head. Those pairs cannot be consumed under FIFO
and disappear at reset. The outstanding demand set can then keep producing
the same starvation pattern. This is a routing/service-interface interaction.

The POQI systems also have failures: at p=1 and two slots every arm has zero
late service. At four slots, persistent pressure obtains .8357 at p=1 and
.3253 at p=.5, while reset pressure obtains 0 and .0850 respectively. These
figures do not isolate routing: storage, reservations, candidate order and
service interaction all differ.

After observing that failure, a **post-hoc mechanism diagnostic**, outside
the fixed primary grid, ran **20 additional trajectories**: diamond, memory
four, p=.5, the same ten seeds and horizon. It compares Q-CAST global FIFO
with **oldest-request-per-pair concurrent consumption**. Routing code, reset,
physical opportunities and offered arrivals remain the same. Later realized
routes may change because consumption changes the pending S-D set.

| Q-CAST service diagnostic | Global FIFO | Concurrent per pair |
| --- | ---: | ---: |
| Throughput [95% CI] | 0 | .8880 [.8582,.9178] |
| Zero-service runs | 10/10 | 0/10 |
| Mean backlog | 210.54 | 2.65 |
| Final backlog | 346.1 | 3.5 |
| Completed mean latency | Undefined | 2.94 |
| Mean allocated qubits | 12.00 | 12.06 |

Concurrent per-pair throughputs are **.48767/.25800/.14233** for 03/01/12;
each class receives service. The allocated-qubit difference is unresolved:
**+.0627 [-.4281,.5534]**. Every rerun FIFO record matches its primary-run
record exactly. This diagnoses the scheduling mechanism; it is not a
prespecified performance arm or a fair concurrent Q-CAST versus FIFO POQI
ranking. Matching concurrent POQI controls remain necessary.

## Additional author-accounting defect

A deterministic nested-demand probe finds a further source behavior beyond
the previously documented duplicate-entry problem. On chain 0-1-2, memory
[1,2,1], p=q=1, requests ordered 02 then 01, Q-CAST creates one physical 02
pair. The author's traversal reports counts **[1,1]**, but physical counts are
**[1,0]**: the apparent destination at node 1 has already been swapped.
`Topo.getEstablishedEntanglements` stops on reaching the destination without
checking that endpoint remains unswapped.

The bridge retains author-reported counts and verifies actual components,
unswapped endpoints and exclusive inputs before useful accounting. It changes
neither P2 nor P4. **3,000 measured native slots** carry an author/physical
count discrepancy flag in the primary run. Native tests also retain a p=q=1
diamond tie case where both paths serve the first S-D pair while the other
receives no physical ebit. Neither behavior was removed to improve results.

## Validation, artifacts and reproduction

The full root suite passed **556 tests, no skips**, in **33.48 seconds**:
443 previous tests plus 113 new tests. Coverage includes pre-outcome capacity
and quota reservation, failed-trial cost, frozen-helper equivalence, batching,
inherited expiry, the known absorbing trace, FIFO/per-pair service, boundary
arrivals, censoring, native reset/recovery, ten earlier reference-case replays,
and deliberate record corruption. A 70-trajectory, 12-slot smoke run preceded
the primary run. The full grid was not expanded after inspecting performance.

Independent replay verified **700 runs, 280,000 slots, 80,432 completions,
21,000 observation fields, 70 group summaries and 90 paired contrasts**.
It reconstructs admission, origins, swap eligibility, physical native paths,
FIFO, queue area, expiry/reset and pair conservation. All source/build and
700 artifact hashes match. The independent service review checked another
**20 runs, 8,000 slots and 3,634 completions**, including all ten exact FIFO
replays. No failed or zero-service trajectory was omitted.

- Primary [manifest](results/qcast/pilot-main-01/manifest.json),
  [report](results/qcast/pilot-main-01/report.json),
  [per-run/per-demand observations](results/qcast/pilot-main-01/observations.json),
  [CSV](results/qcast/pilot-main-01/figures/summary.csv),
  [independent audit](results/qcast/pilot-main-01/independent-audit.json).
- Service [report](results/qcast/pilot-service-diagnostic/report.json),
  [manifest](results/qcast/pilot-service-diagnostic/manifest.json),
  [independent review](results/qcast/pilot-service-diagnostic/independent-review.json).
- [Full test log](results/qcast/pilot-full-tests.log) and
  [nested-demand probe](results/qcast/nested-probe.json).

![All primary conditions with pointwise intervals](results/qcast/pilot-main-01/figures/throughput.png)

The dotted lines show nominal offered rates. Overlapping zero curves are
retained. The figure was visually checked; [PDF](results/qcast/pilot-main-01/figures/throughput.pdf).

From `E:\POQI`, with the pinned author checkout and local Maven cache from
reference validation, use fresh output directories:

```powershell
.\.venv\Scripts\python.exe -B scripts/qcast_pilot.py --output results/qcast/pilot-smoke-01 --horizon 12 --warmup 3 --replicates 1 --seed 6201
.\.venv\Scripts\python.exe -B scripts/qcast_pilot.py --output results/qcast/pilot-main-01 --build results/qcast/pilot-smoke-01/build
.\.venv\Scripts\python.exe -B scripts/qcast_pilot_audit.py results/qcast/pilot-main-01
.\.venv\Scripts\python.exe -B scripts/qcast_service_diagnostic.py --output results/qcast/pilot-service-diagnostic
.\.venv\Scripts\python.exe -B scripts/qcast_pilot_plot.py results/qcast/pilot-main-01
$env:QCAST_PILOT_BUILD = 'E:/POQI/results/qcast/pilot-smoke-01/build'
$env:QCAST_VALIDATION_DIR = 'E:/POQI/results/qcast/validation-03'
.\.venv\Scripts\python.exe -B -m pytest tests -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/qcast-pilot-full
Remove-Item Env:QCAST_PILOT_BUILD, Env:QCAST_VALIDATION_DIR
```

Runner: [qcast_pilot.py](scripts/qcast_pilot.py); POQI wrapper:
[qcast_poqi.py](scripts/qcast_poqi.py); native bridge:
[SlotBridge.kt](scripts/qcast/SlotBridge.kt); independent replay:
[qcast_pilot_audit.py](scripts/qcast_pilot_audit.py); post-hoc diagnostic:
[qcast_service_diagnostic.py](scripts/qcast_service_diagnostic.py).
Without the environment variables, native-artifact tests visibly skip.
Generated data remain under ignored `results/qcast/`.

## Next comparison decision

Retain Q-CAST, but do not use the global-FIFO wrapper as its only workload
baseline. Add matching concurrent-service POQI controls before interpreting
alternative-route performance. Keep the chain storage/cost result as a
conditional finding, retain the two-slot failure, and specify any future
Q-CAST-PI inventory reuse, expiry and demand-cap rules explicitly. Longer
windows, other loads/topologies, swap failures, allocation-rule controls and
physical time calibration are still required before a broad crossover claim.
No existing continuous-time result has been replaced by this pilot.

# Matched concurrent-service follow-up protocol

This fixes the next experiment before its performance runs. The question is
whether the previous diamond result changes when **every system can serve
independent pending source-destination pairs**, and what service, waiting and
resource costs remain after that demand-service difference is controlled.
The earlier [pilot](QCAST_Pilot_Results.md) and its post-hoc Q-CAST-only
diagnostic motivated this targeted follow-up. They are not new replications.
This is a bounded comparison of complete systems, not a general Q-CAST ranking.

## Systems and fixed grid

Cross seven algorithm/storage systems with two service modes:

| Algorithm/storage system | Inventory between slots | Swap/allocation rules |
| --- | --- | --- |
| Q-CAST-Slot | Reset | Pinned author routing, widths and recovery |
| POQI-Slot-balancing | Reset | Frozen balancing and neighbor reservations |
| POQI-Slot-pressure_relaxed | Reset | Frozen pressure relaxation and reservations |
| POQI-PersistentOpportunity-balancing | Retained, no expiry | Same root rules |
| POQI-PersistentOpportunity-pressure_relaxed | Retained, no expiry | Same root rules |
| POQI-Cutoff10-balancing | Retained, inherited cutoff 10 | Same root rules |
| POQI-Cutoff10-pressure_relaxed | Retained, inherited cutoff 10 | Same root rules |

The last four are opportunity-clock wrappers, not the original continuous-time
Poisson-generation simulator. Record **system and service mode separately**;
concurrent Q-CAST must not be labelled `QCAST-Slot-FIFO`. Neither service mode
implements a persistent-inventory adaptation of Q-CAST.

- **Diamond only:** edges `01,02,13,23`; coordinates
  `0=(0,0),1=(1,0),2=(0,1),3=(1,1)`.
- Uniform memory **2 or 4** physical qubits/node; link success **p=1 or 0.5**.
- **D=1, q=1, Delta=1**, two named channel opportunities/edge/slot;
  author recovery enabled with **k=1** and `alpha=-log(p)` on unit-length edges.
- Independent Poisson unit-demand rates `(0,3)=0.5`, `(0,1)=0.25`,
  `(1,2)=0.15`; empty initial queue and inventory.
- **H=400**, warm-up boundary **100**; ten fresh paired seeds **7271-7280**.
- Four physical conditions x seven systems x two service modes x ten seeds:
  **560 trajectories / 224,000 slots**. Do not expand the grid, select seeds,
  or change metrics after inspecting these results.

Fresh seeds separate this follow-up from the diagnostic samples. They do not
remove the fact that the topology and conditions were selected after the
earlier findings. The single-pair chain is a validation control, not another
performance condition or a substitute for retaining the existing two-slot
no-expiry failure case in the project record.

## Service contract and timeline

Both modes see the same full arrival trace and use deterministic arrival/id
ordering. **FIFO** repeatedly serves the global oldest pending request while
a matching physical pair exists; it stops at the first unavailable head.
**Concurrent-per-pair** scans the ordered pending requests and consumes a
matching physical pair whenever available, bypassing unavailable unrelated
requests while preserving oldest-first service within each S-D pair. A pair
can complete only one request. There are no swaps between consumptions in
either mode. Consumption in POQI removes real inventory and frees its actual
endpoint slots and origin reservations.

Keep the pilot timeline unchanged. Requests arrive on `[0,H)` and become
visible at `ceil(arrival)`. At a boundary, finish the preceding slot: expire
due pairs, install successful generation as a batch, settle with frozen
rules/order, serve previously visible requests under the selected mode, then
discard remaining pairs in reset systems. Expose newly visible arrivals only
after that end phase. Persistent systems may consume already-formed cached
pairs at the new slot's start under the same selected mode, without another
swap round. At H finish the preceding slot, but perform no new-start service
or generation; retain final-interval arrivals in the offered workload and
unfinished count.

Measure service at timestamps **(100,400]**, physical activity in slots
starting **100..399**, and queue area over **(100,400)**. Observe Q(100) after
all boundary service at 100. Service mode may change the pending S-D set,
later Q-CAST allocation and later POQI admission through freed inventory;
these feedback effects are part of the system comparison, not a pure
re-accounting of one fixed production trace.

## Physical opportunities, information and accounting

Retain the [pilot physical contract](QCAST_Pilot_Protocol.md). Every selected
channel trial reserves both endpoint qubits for the entire slot, including
failed trials, with at most one trial/channel/slot and no within-slot retries.
Stored pairs occupy endpoint memory but do not permanently occupy a channel.
Existing occupancy plus tentative trials must satisfy total memory; POQI also
keeps its fixed neighbor quotas. Q-CAST retains route-aware allocation and
author ordering. POQI retains its exogenous keyed admission ordering and
original swap predicates/order. Neither policy receives unselected outcomes.

For all systems/modes use identical arrivals and potential link outcomes keyed
by `(seed, topology, slot, physical edge, channel lane)`, with separate
namespaces for demand and admission order. Exclude memory, p, system and mode
from the link key. Reveal only selected outcomes, succeeding iff `U < p`;
do not force equal realized generation when attempt choices differ. Swaps
are deterministically successful here. Charge allocated qubit-time as
`(live endpoint qubits before attempts + 2*selected trials)*Delta`, bounded
by total node capacity. Distinguish stored occupancy, failed reservations,
expiry loss and reset loss. Cutoff outputs inherit the earliest input expiry.

Use author revision **`0a0251dd5f38eb1669ff6abe18ab83436ddbba18`** and
the existing physical-delivery guard from
[reference validation](QCAST_Validation_Results.md). Supply the planner with
unique pending S-D pairs; queue multiplicity remains in the workload wrapper.
Retain raw author delivery counts separately from verified physical ebits
and useful request completions. Neither duplicate counting nor a path prefix
ending at an already-swapped destination is valid service. Author planning,
path width and recovery remain unchanged. Global demand visibility, recovery
information and decision timing retain the established reference contract.

## Outcomes and prespecified contrasts

Primary outcomes are window useful throughput and mean backlog. Also report
backlog growth/final backlog, physical ebits, attempts, failures, swaps,
allocated/stored qubit-time, expiry/reset losses, completed-request latency,
unfinished count/age, and full-cohort restricted waiting
`min(completion,H)-arrival`. Integrate queues from true arrivals, including
pre-visibility waiting. Restricted waiting includes every offered request;
unfinished observations are right-censored, not zero-wait completions.

For **each of the three demand pairs**, report window completions/throughput,
the fraction of trajectories with zero window service, final backlog,
completed latency, unfinished age, and restricted waiting. Distinguish
`window throughput / nominal pair arrival rate` (a load-normalized rate,
possibly above one) from `all-horizon completions / all-horizon offered
requests` (a cohort completion fraction). Do not let aggregate throughput
hide starvation of one pair or compare conditional latency alone.

For each physical condition prespecify paired seed differences:

1. Q-CAST minus each POQI system **under concurrent service** for throughput,
   backlog, costs and per-demand outcomes.
2. Concurrent minus FIFO within each of the seven systems.
3. Pressure relaxation minus balancing within matching inventory lifetime and
   service mode.

Use seed-level means and pointwise 95% Student-t intervals, ten replications
per complete cell; slots are not independent replications. Report zero-service
counts explicitly. Attempts/completion and swaps/completion are window
activity ratios, undefined at zero service; report defined/undefined counts,
and for paired ratios use only pairs with both values defined while stating
their number. Keep every zero-service run in throughput/backlog/wait summaries.
These are exploratory intervals without multiplicity correction; crossing zero
does not demonstrate equivalence. H=400 does not establish queue stability,
and a fully occupied diamond is not automatically a certified absorbing state.

## Execution gates and reproducibility

Implement the generalized service harness in new files, preserving historical
pilot/diagnostic sources and artifacts. Before interpreting performance:

- Check FIFO regression against saved old pilot records across all seven
  systems and concurrent Q-CAST against the earlier diagnostic.
- Check single-demand chain equality between modes; exercise bypass,
  oldest-within-pair ordering, physical consumption/exclusivity, freed
  reservations, boundary arrivals, cutoff expiry and cached start service.
- Keep the deterministic known two-slot absorbing-failure regression.
- Independently replay resource limits, exclusivity, service eligibility and
  consumption, waiting-area conservation, per-demand observations and paired
  summaries from raw records; the auditor must not reuse the service/observer
  implementation it is checking.
- Record exact commands, source/build hashes, author revision, configurations,
  complete raw trajectories, audit findings and test outcomes in ignored
  `results/qcast/` artifacts and a separate concise results document.

Retain failed software-run logs, stalled trajectories and zero-service cases.
A missing or invalid trajectory is an explicitly reported study failure, not
an omitted replicate. The results document must separate executed evidence
from remaining gaps. The recommendation remains separately labelled shared
slotted and persistent-opportunity comparisons; original continuous-time
results retain their own model and interpretation.

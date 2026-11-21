# Matched Q-CAST pilot protocol

This protocol is fixed before inspecting pilot performance results. It extends
the [comparison design](QCAST_Comparison_Plan.md) with a bounded, executed-next
system comparison; it does not implement Q-CAST-PI or change the existing
continuous-time simulator. The pinned author reference and its limitations
remain those in [QCAST_Validation_Results.md](QCAST_Validation_Results.md).

## Question and arms

Under the same physical opportunity budget and offered unit-request trace,
how much useful service do the following systems provide, at what waiting,
memory-time and operation cost?

1. **Q-CAST-Slot-FIFO:** actual pinned author allocation/recovery and slot reset,
   with a labelled unit-workload/global-FIFO accounting wrapper. The planner
   receives the unique pending S-D set; duplicate requests remain outside the
   author interface. Verify physical deliveries using unswapped source and
   destination endpoints and successful internal swap connections. Retain raw
   author-reported counts separately: the author traversal may count a path
   prefix whose apparent destination qubit has already been consumed by a
   longer path. This accounting guard changes neither allocation nor swaps.
   Verified produced ebits and useful FIFO completions are separate measures.
2. **POQI-Slot-balancing** and **POQI-Slot-pressure_relaxed:** frozen root swap
   predicates, priority and neighbor reservations, batch generation followed by
   settling and FIFO service, then discard all remaining inventory.
3. **POQI-PersistentOpportunity-balancing** and
   **POQI-PersistentOpportunity-pressure_relaxed**, each with **no expiry** and
   **inherited cutoff 10**: same opportunity clock and root rules, retaining
   inventory between slots. These four arms are new timing wrappers, not the
   previously studied Poisson-success continuous-time system.

The seven arms compare complete systems. Q-CAST's route-aware allocation and
POQI's fixed neighbor reservations remain different, deliberately visible
design choices. Shared-slot arms control reset timing; persistent arms expose
the benefit and cost of retained inventory. No result isolates a pure routing
effect, establishes performance of a persistent Q-CAST adaptation, or settles
the full crossover hypothesis. Concurrent-service and allocation-rule controls
remain later work.

## Fixed small grid

- **H=400** slots of **Delta=1** abstract time unit. Primary service timestamps
  are **(100,400]**; physical-cost intervals are slots starting **100..399**,
  and backlog area is integrated over **(100,400)**. Empty initial inventory
  and queue. State at 100 is measured after service at that boundary.
- **Ten paired seeds, 6271-6280**. Replication units are seeds, not slots.
- **D=1**, deterministic successful swaps **q=1**. Each physical edge provides
  **two named channel opportunities per slot**. One selected opportunity is
  one link trial lasting the entire slot; independent trial success is
  **p=1 or p=0.5**. There are no hidden within-slot retries.
- **Chain:** nodes `0-1-2`, uniform memory **2,3,4** qubits/node; endpoint
  request rate `(0,2)=0.75`.
- **Diamond:** edges `01,13,02,23`, square coordinates
  `0=(0,0),1=(1,0),2=(0,1),3=(1,1)`; uniform memory **2 or 4**;
  request rates `(0,3)=0.5`, `(0,1)=0.25`, `(1,2)=0.15`.
- Ten topology/memory/success conditions, seven arms and ten seeds give
  **700 short trajectories / 280,000 slots**. No grid expansion or seed
  selection follows inspection of performance.

All physical edges have unit length, permitting author probability
`exp(-alpha*length)=p` with `alpha=-log(p)`. Author recovery is enabled with
**k=1**, also recorded in the run manifest.
Two channels/edge are intentional: with only one and a full reset each slot,
balancing could never obtain its required two pairs on each input, regardless
of nominal memory. That structural zero is not an informative high-memory
comparison.

## Timeline, physical budget and common randomness

Generate continuous Poisson unit requests on **[0,H)** once per topology/seed.
Arrival at time `a` becomes visible for decisions at `ceil(a)`. All arms use the
same arrival times, identities and FIFO ordering, including deterministic
tie-breaking. Requests during the last slot remain offered and unfinished at
H. Record their true arrival times for latency and backlog integration.

At an integer decision epoch, first finish the preceding slot: remove pairs
whose inherited deadline is due, install that slot's successful generation as
a batch, execute the unchanged settling order, consume eligible FIFO demand,
and clear remaining pairs in reset arms. Then expose newly visible arrivals.
Persistent arms consume already-formed pairs from stored inventory before
planning new attempts; they do not run an additional swap round at the start.
Swapping runs only after the end-slot generation batch. This explicitly
permits a cached pair to serve at the arrival's visibility epoch and differs
from the root simulator's settling after each continuous event; candidate
rules and swap order are unchanged. At H, complete the preceding slot, but start no new
generation or newly visible service. Count all service at 100 outside the
measurement window and all eligible preceding-slot service at 400 inside it,
in every arm. Boundary observations and event selection must use these
conventions consistently.

All attempt selections precede revelation of the slot's random outcomes.
Reserve both endpoint qubits for every selected trial, including trials that
will fail. POQI checks existing occupancy plus tentative reservations against
total capacity and each generation-neighbor quota. A channel has at most one
trial per slot; old stored pairs occupy memory but do not permanently occupy
that channel. Q-CAST retains its author allocation/ID ordering. POQI's channel
admission order uses a separate exogenous keyed priority per slot, avoiding a
fixed first-edge scheduling advantage; this ordering is part of its named
opportunity wrapper, not a change to the swap predicate.

Use a shared SHA256-keyed potential uniform outcome by
`(seed, topology, slot, physical edge, channel lane)`. Exclude policy, capacity
and success-probability setting from the key. A policy observes only selected
trials, and succeeds iff its potential uniform value is below p. Demand and
admission-order keys use separate namespaces. Different policies may select
different trials and realize different successful supplies. Author display
RNG draws are overwritten by the supplied operative link outcomes. With q=1
there is no stochastic swap-coupling ambiguity in this pilot.

Charge each interval's allocated qubit-time as
`(pre-interval live endpoint qubits + 2 * selected trials) * Delta`.
This includes unsuccessful in-flight reservations and must not exceed
`sum_v M_v * Delta`. Distinguish stored-pair occupancy from reserved allocation.
Release reservations at trial completion; no within-slot reuse is allowed.
Cutoff 10 begins when a successful elementary pair becomes available and
outputs inherit the earliest input deadline. Slot-end discard and expiry are
different losses. Native Q-CAST's reset frees all assigned resources.

## Measurements and interpretation

Primary outputs are late-window useful completions/time and time-average
backlog. Also report per-demand service; completed-request latency, explicitly
conditional on completion; unfinished counts and ages; and full-horizon
restricted waiting time `min(completion,H)-arrival` for every offered request,
including right-censored requests. Integrate backlog from true arrival times,
including the period before visibility. Verify full-horizon waiting-area
conservation. Any measurement at H must follow one declared convention and
the final unprocessed arrivals must not disappear from the backlog.

Report selected, skipped, capacity/quota-blocked and failed opportunities;
generated elementary pairs; swaps; useful completions; final inventory;
reset/expiry discards; peak resource allocation; and stored/allocated
qubit-time. Count delivered-demand ebits separately from useful FIFO service;
surplus ebits are not completed requests. Attempts/completion and
swaps/completion are window activity ratios and remain undefined at zero
service. They are not the lineage cost of a completed pair if its inputs
predate the window.

For each fixed condition, summarize ten-seed means and pointwise 95% Student-t
intervals. Predeclare paired differences of Q-CAST minus each POQI arm for
throughput and backlog, and pressure minus balancing within matching reset/
lifetime arms. Pair by topology/seed and physical workload, not by realized
successes. These are exploratory finite-window estimates without a
multiple-comparison correction; intervals crossing zero do not establish
equivalence, and backlog observations do not prove stability.

Retain every failed, zero-service and stalled case. Separately record the
sufficient no-expiry chain absorbing certificate (pending endpoint demand,
full center, all live pairs from center to one endpoint). This certificate is
not a complete deadlock detector. Replay the existing two-slot absorbing trace
as a deterministic regression even if synchronized pilot batches never enter
it. Validate attempt reservations, failed outcomes, exclusivity, expiry/reset,
FIFO blocking, boundary arrivals, and independent event/accounting replay
before interpreting results. Preserve failed software runs and their logs;
final performance summaries include only complete, validated runs, with any
missing trajectory reported as a study failure rather than silently omitted.

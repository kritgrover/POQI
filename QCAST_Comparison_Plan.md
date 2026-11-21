# Q-CAST comparison design

## Reference and scope

Use the authors' [QuantumRouting](https://github.com/sshi27/QuantumRouting/tree/0a0251dd5f38eb1669ff6abe18ab83436ddbba18)
at **`0a0251dd5f38eb1669ff6abe18ab83436ddbba18`**. Its README identifies
the [SIGCOMM 2020 paper](https://doi.org/10.1145/3387514.3405853),
*Concurrent Entanglement Routing for Quantum Networks: Model and Designs*;
`Plot.kt` maps `OnlineAlgorithm` to Q-CAST. This revision includes a later
resource-utilization fix; it is not established as the exact publication-time
revision. [arXiv v3](https://arxiv.org/abs/1909.09329v3), dated 25 October 2019,
has the earlier title *Modeling and Designing Routing Protocols in Quantum
Networks*. Do not treat the preprint, paper and current code as identical.
See [validation results](QCAST_Validation_Results.md) for the audit, executed
fixtures and source differences.

The reference is the actual Kotlin implementation, run headlessly through a
small phase-level harness. No production POQI policy is changed. A future port
must reproduce path allocation and controlled outcomes against this reference
before it is used for performance claims. A shortest-path baseline or POQI's
`physical` diagnostic is not Q-CAST.

For a path of `h` edges and width `w`, the code's metric is
`q^(h-1) E[min_e Binomial(w,p_e)]`. It accounts for parallel successful links,
not just hop count. `calCandidates` searches widths downward and stops at the
first feasible width for each S-D pair; P2 repeatedly allocates the highest
metric candidate among pairs, reserving `w` qubits at endpoints and `2w` at
intermediates plus `w` channels per edge. Spare resources fund recovery routes.
P4 uses realized link outcomes to repair selected main-path segments and swap.
Recovery addresses link-generation failures, not retry after failed swapping;
assigned qubit/channel capacity stays reserved through slot end.
The code's `k` limits separation of recovery endpoints along the main path;
it is not a detour-length limit or an enforced distributed information boundary.

## Recommendation and experiment labels

Use **separately labelled experiments in both models**. Retain native slotted
Q-CAST as the fidelity anchor. The main memory/expiry question needs a persistent
arm; a slotted reset alone cannot test inventory persistence or its absorbing
failure. Conversely, a persistent adaptation alone cannot establish a result
about original Q-CAST.

- **Q-CAST-native:** pinned algorithm, independent slots, concurrent S-D set,
  route-aware allocation, all delivered ebits. This milestone validates small
  cases only.
- **Q-CAST-PI:** proposed persistent-inventory adaptation. Keep the path metric,
  major/recovery allocation and exclusive resources where applicable; replan at
  declared epochs using remaining physical capacity and explicit inventory.
  Reusing aged direct or end-to-end pairs, expiry, demand caps and partial paths
  require new rules and tests; they are not implemented or validated here.
- **Q-CAST-PI-FIFO:** explicitly named variant with the root global FIFO; planner
  sees the pending S-D set, but useful consumption obeys the head of the queue.
  **Q-CAST-PI-concurrent** instead consumes oldest requests independently per
  S-D pair. Measure this scheduling difference rather than attribute it to
  routing. A corresponding POQI concurrent-service arm is a separately labelled
  wrapper, not a replacement for the frozen FIFO experiments.
- **POQI-Slot:** optional shared-slot control using the unchanged balancing or
  pressure predicate, batch generation then settling, and reset at slot end.
  Those timing/reset changes must be named; its results do not replace the
  continuous-time results.

## Matching contract for the next phase

| Dimension | Required comparison rule |
| --- | --- |
| Time | Declare slot/attempt duration `Delta` in the same time unit. Native Q-CAST performs allocation, link generation, link-state observation and swapping once per slot. The root currently settles after each continuous-time event. Report rates per elapsed time and decision frequency; equal rates do not remove batching effects. |
| Persistence/expiry | Native `work()` resets links, assignments and qubits each slot. Persistent arms retain physical endpoint slots until consumption, swap release or inherited minimum-input deadline; expiry must not refresh at a swap. Test no expiry and cutoff 10 separately. Slot-end disposal is a distinct loss category. |
| Memory/channels/attempts | Specify node qubits `M_v`, parallel channels `C_e`, per-channel trial opportunities and duration, and per-edge attempt budget/time. Reserve both endpoint qubits while an attempt is in flight. Count occupied and reserved qubit-time, attempted, skipped and blocked opportunities, successes and unused channels. Route allocations cannot reuse a reserved channel/qubit. |
| Success | Start with `D=1`, link success `p=1`, swap success `q=1`. Then introduce controlled failures before stochastic runs. The authors' `p_e` is an effective link success probability; multiple underlying trials need an explicit trial count and stopping rule. For `n` independent trials, `p_eff=1-(1-p_trial)^n`; expected realized trials also affect cost. |
| Demand/accounting | Use the same exogenous unit-request arrival trace in workload arms. At each decision epoch expose declared pending pairs; one ebit can retire at most one eligible request. Keep multiplicity outside the native interface: repeated entries of the same unordered S-D pair double-count ebits. Record generated endpoint ebits, useful completions, surplus/discarded ebits, remaining inventory and backlog separately. Native saturated S-D throughput remains a separate metric; do not cap it silently to one ebit per pair. |
| Allocation | Native Q-CAST assigns qubits to selected routes. Root reserved admission divides slots by physical neighbor and retains origin identity across swaps. Preserve each native rule in system comparisons. Add explicitly labelled route-aware/fixed-reservation controls, crossed with FIFO/concurrent service, before attributing differences to the swap rule alone. |
| Information | P2 uses topology, channel probabilities, qubit budgets and concurrent demands before current-slot success is known. Paper P4 uses limited link-state information; the code has shared topology access and no message latency. Root policies read partner/output counts without communication cost. Label ideal information and record decisions/state accesses; do not claim equal classical overhead until both have a common message/delay model. |

The root's `generation_capacity` currently drives **successful-pair Poisson
arrivals**, with no failed trial, channel identity or attempt duration
([adapter](src/poqi/simulation/sequence_adapter.py)). It cannot simply be equated
to Q-CAST's channels/slot or inferred as `attempt_rate * p` under occupancy and
adaptive allocation. A separate common opportunity scheduler is a prerequisite
for physical-cost comparisons; preserve the existing simulator and policy
predicates, and validate new scheduler/admission semantics independently.

Couple **potential** outcomes using a shared exogenous ledger keyed by seed,
physical edge/channel, opportunity epoch and trial index. A policy reveals an
outcome only if it attempts that opportunity. Different attempt choices may
produce different successes. Do not share a mutable random stream indexed by
policy action count or force equal successful arrivals. Couple swap outcomes
only for matching physical input identities/lineages and pivot; otherwise use
independent keyed draws. Include skipped opportunities and failed trials in
the ledger. The deterministic validation fixtures are not this future coupling
implementation.

## Gates and retained cases

Before sweeps, validate direct links, width greater than one, chain, asymmetric
diamond, competing demands, recovery, failed links/swaps, reset and resource
conservation against the pinned reference. Add expiry and persistent-input
reuse tests only when Q-CAST-PI exists. Replay the root two-slot no-expiry
absorbing trace unchanged; retain balancing's low-memory zero-service cases,
failed recovery and every stalled run.

Then preregister fixed memory/channel budgets, attempts/time, topology/demand
seeds and warm-up/horizon windows. Include alternative routes and shared
bottlenecks, not only chains/stars. Report paired seed contrasts, per-demand
service, censored waiting times/backlog, stall counts, qubit-time, attempted
generation, swaps/completion (undefined at zero service) and reset/expiry
losses. Keep workload-limited throughput distinct from saturated ebit capacity.
Large sweeps, hardware calibration, persistent adaptation, distributed overhead
and any parity/performance claim remain outside this milestone.

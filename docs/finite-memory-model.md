# Finite-memory model and simulator

POQI separates a rate-based analytical model from an executable policy. The LP
answers a conditional question: for supplied mean pair-buffer residence times,
what average memory supports a fraction of a matching unlimited-memory optimum?
The SeQUeNCe adapter measures what a concrete policy achieves with integer slots,
stochastic successful generation, explicit requests, and optional expiry. Agreement
between those models requires checking their assumptions and residence times.

All new source, configurations, tests, and results are owned by the root project.
Neither `SeQUeNCe` nor `quantum-network` needs to be the working directory. The
existing examples remain unchanged references.

## Provenance and comparison

The LP's starting point is
[`SeQUeNCe/example/path_oblivious_corrected/lp.py`](../SeQUeNCe/example/path_oblivious_corrected/lp.py)
at SeQUeNCe revision `1223767054660dbfec1fcb901a4dfaf30be2d028`. The two included
papers are versions of the same work, *Path-Oblivious Entanglement Swapping for
the Quantum Internet*. The final [HotNets paper](../papers/hotnets25-final271.pdf),
Section 3, supplies the lossless pair-rate convention. The earlier
[arXiv version](../papers/2509.13993v1.pdf) has a different loss-factor expression;
that factor is not used as a deterministic decoherence model.

The historical author simulation reference is
`quantum-network@7c57be549c275509b1674aaab3f7341c955041db`, separate from the
current Rust checkout at `5d8ed3ee061755d32d9045729518e82e3f5d9e89`.

| Aspect | `path_oblivious` | `path_oblivious_corrected` | Root `poqi` |
| --- | --- | --- | --- |
| Purpose | Literal author-code reproduction | Corrected dynamics and controlled comparisons | Conditional memory sizing and hard-slot policy experiments |
| Inventory | Unlimited pair counts | Unlimited nonnegative pair counts | Individual pair IDs, finite or explicitly unlimited slots, endpoint occupancy |
| Swaps | Preserved author transitions | One currently preferred swap per visit, then recompute | Corrected preference available; physical and disabled policy options |
| Time | One author iteration per event | One iteration per event | Declared time units converted explicitly to SeQUeNCe ticks |
| Generation | Historical random batches; `capacity` is initial inventory | Historical or controlled batches; LP separately uses rate `capacity` | Successful physical pair arrival rate named `generation_capacity` |
| Requests | Historical blocking FIFO sequence | Blocking FIFO; matched replay inputs | Independent offered Poisson arrivals and an unbounded global FIFO; deterministic traces also supported |
| Lifetimes | No expiry | No expiry | Optional inherited hard deadline; swapping never renews it |
| LP | No independent finite-memory model | Minimum generation for fixed completion rates, with surplus allowed | Stationary balances by default, legacy surplus mode, proportional throughput, minimum mean-memory sizing |
| Memory model | Unlimited | Unlimited | LP: prescribed mean occupancy; simulation: hard integer slots |
| Reporting | Historical metrics and stopping | Both overhead definitions, accounting, replay and replicate statistics | Pair service/backlog, occupancy, blocking, expiry, censored episodes, LP residuals and sizing |

The new simulator does not reproduce the old iteration-based trajectories or
historical overhead curves. Its changed arrival process, time semantics, admission
policy, and deterministic node ordering are explicit experimental choices. The
two earlier runners remain appropriate for author parity and their existing
controlled comparison workflow.

## LP equations and units

For every unordered node pair `p={x,y}`, including nonphysical pairs, let `g_p`
be admitted successful physical generation, `s_i(x,y)` the swap rate at pivot
`i` producing `p`, and `c_p` completed requests per declared time unit. Generation
is bounded by `0 <= g_p <= generation_capacity_p`, with zero capacity on nonedges.
The positive integer `D=distillation_pairs` consumes `D` raw pairs from each swap
input and `D` raw pairs per completed request. Swaps produce one raw output pair.

The arrival and useful departure rates are

```text
a_xy = g_xy + sum_i s_i(x,y)
b_xy = D * [c_xy + sum_i (s_x(i,y) + s_y(i,x))]
```

The default lossless stationary balance is `a_xy = b_xy`. The legacy mode uses
`a_xy >= b_xy` and reports `a_xy-b_xy` as unallocated surplus. It is a resource
feasibility convention, not stationary inventory, voluntary disposal, or expiry.
Neither formulation imposes physical scheduling constraints.

For prescribed positive `tau_xy=mean_residence_time_xy`, Little's law supplies

```text
q_xy = a_xy * tau_xy
L_x = sum_(y != x) q_xy <= M_x
```

Each pair occupies one slot at each endpoint. A virtual output charges its
endpoints, not the measured pivot. `D` already changes resource rates and is not
multiplied into occupancy a second time. Rates and residence coefficients must
use the same declared `time_unit`. Assembly exposes sparse arrival `R`, incidence
`H`, and memory `B = H diag(tau) R` operators. There are `n(n-1)/2` pair buffers and
`n(n-1)(n-2)/2` swap-rate variables, so assembly remains cubic in node count.

The primary objective maximizes `alpha` subject to `c_p=alpha*demand_rate_p` and
`0 <= alpha <= 1`. It preserves the supplied demand mix. The unlimited-memory
baseline removes only memory rows, retaining demand, generation, `D`, and balance
semantics. An optimum of one means the supplied demand cap was met; it does not
establish network saturation. A zero proportional baseline means at least part
of the demand mix cannot be served, so fraction-based sizing is reported as
nonserviceable instead of assigning a misleading zero budget.

For target fraction `eta`, sizing fixes `c_p=eta*alpha_infinity*demand_rate_p`
and reoptimizes generation and swaps while minimizing `m` with `L_x <= m`.
The Python API also accepts a positive complete `memory_shape` mapping and then
uses `L_x <= m*memory_shape[x]`. Reading occupancy from an arbitrary unlimited
optimizer is not this minimum-memory calculation. Default lexicographic solves
minimize generation after maximizing satisfaction or minimizing memory.
Allocations can remain nonunique.

Returned diagnostics include admitted generation, swaps, completions, arrivals,
pair and node occupancy, memory slack, limiting nodes, unallocated surplus,
solver status, assembly/solve time, and independent balance, memory, and bound
residuals. A solver success flag alone is not accepted if these checks fail.

The solver normalizes rate and memory variables and scales constraint rows before
calling HiGHS. Acceptance uses dimensionless relative residuals for each balance,
memory constraint, and bound; absolute residuals are retained as diagnostics.
Extremely heterogeneous coefficients can still produce `numerical_failure`.
That status is a numerical limitation and must not be interpreted as physical
infeasibility.

## Prescribed residence times and expiry

`mean_residence_time` is an externally supplied sensitivity coefficient. It is
neither inferred from inverse generation capacity nor silently set to a cutoff.
A pair-buffer episode ends whenever a pair is consumed, used as a swap input, or
expires. A swap output starts a new episode, while its surviving physical qubits
retain their lifetime constraints.

Scaling every residence coefficient by `k>0` scales the minimum sizing budget
by `k` under otherwise identical assumptions. Such a sweep is an analytical
consistency check, not evidence of a new network-size scaling law. Heterogeneous
coefficients can be supplied for all unordered pairs. Their declared source is
recorded in `residence_time_source`.

The simulator's cutoff creates a deadline at generation and assigns every swap
output the earliest input deadline. Expiry removes the pair at that deadline;
it does not reset at a swap. This is a conservative lifetime abstraction, not a
fidelity or purification model. A lossless LP remains lossless even when the same
configuration requests a cutoff simulation, so it is not a matched finite-cutoff
throughput bound.

Measured completed-episode means and window-restricted means are diagnostics.
Surviving episodes are censored at the observation boundary. Their age contribution
is included when checking the occupancy integral against total episode residence.
That finite-window accounting identity does not make a fitted mean predictive.
Before forecasting a new load, budget, or policy, calibrate independently and
evaluate on held-out configurations, or justify componentwise residence bounds.
The implementation does not perform such a calibration automatically.

## SeQUeNCe execution and policy

`poqi.simulation.run_simulation` imports SeQUeNCe's real `Timeline`, `Event`, and
`Process` classes when invoked. LP imports do not require the simulator. SeQUeNCe
owns event execution and time; `ticks_per_time_unit` converts the declared abstract
units to integer timeline ticks. Its kernel uses picosecond-sized ticks, but this
adapter does not claim that a configured abstract unit is a calibrated second.

Successful generation and offered requests use independent Poisson streams per
physical edge and demand pair. Keeping topology, demand ordering, seed, and horizon
fixed matches exogenous arrivals across memory budgets; policy decisions do not
advance those streams. Poisson times are rounded to the nearest tick. Deterministic
`trace` entries replace random arrivals for small validation cases.

Same-time priority is expiry, generation, explicit swaps, requests, then the finish
marker. All pairs due at a timestamp are purged before policy actions at that time.
Each event before the observation boundary is followed by automatic swaps to quiescence and FIFO
draining. Automatic swaps therefore also run within each generation event; they
do not wait for every same-tick generation event. Expiry events refer to immutable
pair IDs, so an old event cannot delete a replacement pair. Arrivals at the horizon
are excluded; expiries at that boundary are processed before recording final state,
without triggering further swaps or request service.

Admission is atomic at both endpoints. A rejected arrival occupies no slots. A
swap consumes `D` pairs from each input and reuses the surviving endpoint slots;
it does not require an extra output slot. For `D=1`, two occupied pivot slots are
physically sufficient. For general `D`, a swap releases `2D` pivot slots and
`D-1` at each output endpoint.

Admission policies are:

- `reserved` (default): divide each node's integer slots across its physical
  neighbors, assigning any remainder in graph node order. Reservations follow a
  local qubit's original generation edge through later swaps. An input cannot
  consume another neighbor's reservation. This prevents the fill-one-input-first
  chain deadlock when both inputs have sufficient positive quotas, but can leave
  memory unused. A budget smaller than the physical degree leaves zero quotas
  for some neighbors; reservations do not guarantee general service.
- `tail_drop`: admit whenever both endpoints have free slots. This can fill a
  pivot with one input and block the other forever without expiry or consumption.

Recovery is off by default (`recovery_policy: "none"`). With
`recovery_policy: "drop_when_stuck"`, a generation that admission would reject
may evict the pair that holds its slot. At each blocked end the candidate is the
longest-stored pair in the contested slots: a qubit generated toward the same
neighbor under `reserved`, any qubit at the node under `tail_drop`. An
elementary pair of the same link is never a candidate, and a candidate must have
been stored for at least `stuck_patience` since it was generated or produced by
a swap. Nothing is dropped unless every blocked end has a candidate. The rule
needs no clock events and no knowledge of demand. Drops are counted as
`stuck_drops`. [Results and limits](../Recovery_Baseline.md)

Automatic swap policies are:

- `balancing` (default): select at most one currently preferable output per node
  visit, then recompute on later visits. It requires
  `C_xy + 1 <= min(C_ix-D, C_iy-D)`, prefers the smallest output count, and uses
  graph node order for ties. Repeated node passes stop at local quiescence.
- `pressure_relaxed` also permits equality in the post-swap buffer comparison
  when a swap frees a full pivot or a full positive input-origin reservation.
- `pressure_oriented` applies that same pressure policy to single-pair swaps
  (`distillation_pairs=1`). At a pivot the two selected qubits must have been
  generated toward different physical neighbors. This applies even when their
  current partners are remote. The original pressure policy must first permit
  the candidate partner pair. Within each partner buffer the guard considers
  inputs in earliest-deadline, admission-time, then pair-ID order and selects
  the first eligible combination, checking pressure on the actual inputs.
  Explicit trace swaps under this policy also require different orientations.
  [Two-slot queue theorem](../Guarded_Chain_Theorem.md) · [Source of the orientation rule: Talsma, Iñesta and Wehner, Phys. Rev. A 110, 022429 (2024), Algorithm 1, step 3.2](https://doi.org/10.1103/PhysRevA.110.022429) · [How it differs from the 2023 Iñesta–Wehner condition](../Guarded_Chain_Theorem.md#source-of-the-rule-and-what-is-new)
- `physical`: choose a feasible swap without the balancing threshold, using the
  same minimum-output preference. This is a diagnostic policy, not an optimal
  routing or demand-aware algorithm.
- `none`: disable automatic swaps; explicit trace swaps still test physical
  feasibility.

For `D=1`, a pivot with one hard slot cannot swap. Budgets two or three allow
physical swaps but cannot satisfy the balancing predicate for an empty output.
With four slots and two pairs on each input, a preferred swap becomes possible.
Heuristic refusals and infeasible explicit swap attempts are reported separately.

`service_order: "per_pair"` gives each demand pair its own FIFO, so a pair that
cannot be served does not hold back the others. The default `"fifo"` keeps one
global queue.

Every result has a `service_continuity` block for the window
[`measure_from`, horizon). An interruption of a demand pair is an interval in
which one of its requests waits and none completes. Arrivals do not restart it.
A completion ends it and starts the next one if a request still waits. Lengths
are clipped to the window, and the interval open at the horizon counts with its
observed length. The block reports, per pair and for all pairs together, the
number of interruptions, their total, mean and longest length, and the trailing
one. With `outage_threshold` set, interruptions at least that long are counted
as outages with their share of the window. A pair is `starved` if something
waited in the window and nothing completed. The block also gives the least
satisfaction over pairs and Jain's index of the satisfactions.

The global FIFO blocks at an unserviceable head request. Requests are not dropped,
expired, or throttled. Under overload the backlog can grow without bound; completed
request latency is consequently not a stationary all-request latency estimate.
Reports retain unserved requests, final queue ages, service for every demand pair,
and queue growth. All reported observations start at initialization with no
discarded warm-up. A short pilot establishes execution, not stationarity or precision.

## Configuration and root commands

Use a dedicated root environment and the local simulator checkout:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,simulation]"
.\.venv\Scripts\python.exe -m pip install --no-deps -e ./SeQUeNCe
.\.venv\Scripts\python.exe -m poqi sequence-smoke
```

For LP-only use, install `.[dev]`; the simulation extra and SeQUeNCe installation
are unnecessary. The minimal simulation extra supports this adapter's imports,
not every notebook or hardware feature of the SeQUeNCe distribution.

Configurations use explicit node and pair records to preserve string versus
integer labels and detect duplicate reversed pairs:

```json
{
  "nodes": [0, 1, 2],
  "edges": [
    {"nodes": [0, 1], "generation_capacity": 1.0},
    {"nodes": [1, 2], "generation_capacity": 1.0}
  ],
  "demand_rate": [{"pair": [0, 2], "rate": 1.0}],
  "demand_normalization": "One endpoint pair at one request per abstract time unit",
  "mean_residence_time": 1.0,
  "residence_time_source": "Prescribed sensitivity coefficient; not calibrated",
  "memory_slots": 4,
  "time_unit": "abstract",
  "distillation_pairs": 1,
  "balance_mode": "stationary",
  "simulation": {
    "horizon": 100.0,
    "seed": 271,
    "ticks_per_time_unit": 1000000,
    "cutoff_time": null,
    "swap_policy": "balancing",
    "admission_policy": "reserved",
    "request_regime": "offered",
    "recovery_policy": "none",
    "stuck_patience": 0,
    "service_order": "fifo",
    "measure_from": 0,
    "outage_threshold": null
  }
}
```

`memory_slots` must be explicitly present: `null` disables limits, a number applies
uniformly, or records `{"node": 0, "slots": 4}` cover every node. Fractional budgets
are valid only for the average-memory LP; simulations require integer slots.
`mean_residence_time` accepts a positive scalar or a complete record list
`{"pair": [0, 2], "value": 1.0}` covering physical and virtual pairs. Unknown
parameters, missing coefficients/budgets, self-pairs, duplicate reversed pairs,
negative/nonfinite numbers, and duplicate JSON object keys fail explicitly.

The optional `simulation.initial_pairs` lists physical-edge records
`{"endpoints": [0, 1], "count": 1, "age": 0}`. The current implementation starts
from empty inventory by default and accepts only zero-age initial pairs, subject
to admission and slot constraints. A deterministic `simulation.trace` lists events
with `time`, `kind`, `endpoints`, optional `count`, and a `pivot` for swaps. Trace
times must resolve to integer ticks and lie before the horizon. `record_events`
controls detailed event retention.

```powershell
.\.venv\Scripts\python.exe -m poqi lp solve --config configs/memory/chain.json
.\.venv\Scripts\python.exe -m poqi lp min-generation --config configs/memory/chain.json
.\.venv\Scripts\python.exe -m poqi lp size-memory --config configs/memory/chain.json --fraction 0.9
.\.venv\Scripts\python.exe -m poqi simulate --backend sequence --config configs/memory/chain.json --output results/memory/chain-simulation
.\.venv\Scripts\python.exe -m poqi simulate --backend sequence --config configs/memory/cutoff.json --output results/memory/cutoff-simulation
.\.venv\Scripts\python.exe -m poqi experiments memory-sweep --config configs/memory/scaling.json --output results/memory/scaling
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp E:/POQI/tmp/root-tests
```

LP commands print JSON and optionally accept `--output` for saved artifacts.
Simulation and experiment commands save their configuration, provenance, and
results beneath the requested root-owned output directory, which must not already
exist. `sequence-smoke` verifies the imported SeQUeNCe source
path and observes actual timeline events.

The Python interface uses ordinary NetworkX graphs and tuple-keyed mappings:

```python
import networkx as nx
from poqi.lp import solve_throughput, size_memory
from poqi.simulation import run_simulation

graph = nx.path_graph(3)
nx.set_edge_attributes(graph, 1.0, "generation_capacity")
demand = {(0, 2): 1.0}
throughput = solve_throughput(
    graph, demand, mean_residence_time=1.0, memory_slots=1.0
)
sizing = size_memory(graph, demand, mean_residence_time=1.0, fraction=0.9)
simulation = run_simulation(graph, demand, memory_slots=4, horizon=100, seed=271)
assert throughput.success and sizing.success
print(throughput.alpha, sizing.memory_budget)
print(simulation.to_dict()["completed_requests"])
```

For that chain, the analytical values are `alpha=0.5` at mean budget one and
minimum uniform mean budget `1.8` for 90% of the unlimited optimum. A pivot with
one hard slot still cannot perform any swap. This counterexample is the reason
LP memory and hard slots are separate interfaces rather than interchangeable
interpretations of the same number.

## Sweeps and interpretation

Analytical sweeps vary mean-memory budgets, target fractions, residence multipliers,
and offered-demand multipliers on the supplied graph. Direct, chain, star, cycle,
and full-grid configurations make topology explicit. A full grid is different
from the historical shuffled overlay that stops adding edges once connected.
Node counts, generation normalization, total offered demand, and residence source
must stay visible when comparing network sizes or endpoint concentration.

Optional simulation replicates compare each integer budget with the same policy
under unlimited storage. Replicates use independent seeds, while a replicate's
seed is shared across budgets to match exogenous arrivals. The unlimited-policy
simulation isolates storage effects within a policy; the unlimited LP also
removes scheduling, admission, and FIFO restrictions. These two references answer
different questions.

Per-run data retain service by pair, occupancy by node, queue growth, rejections,
expiry, swap counts, and episode statistics. Compare both aggregate completion and
the least-served demand-pair fraction against a proportional target: aggregate
service alone can hide starvation. Student-t intervals across independent
replicates summarize sampling variation; checkpoints from one run are not
independent replicates. Single-replicate results do not have confidence intervals.
Numerical tables and plots are pilot outputs unless horizon and replication
adequacy have been evaluated independently.

Each sweep writes `manifest.json`, `lp.csv`, `sizing.csv`, and detailed LP/sizing
records under `runs/lp-*.json` and `runs/size-*.json`. When simulation is enabled,
it adds `simulation.csv`, `summary.csv`, and `runs/simulation-*.json`. Per-node
occupancy and per-pair service remain available in those JSON records. With
Matplotlib installed, `memory-sweep.png` plots the LP sensitivity curves and
simulation throughput with replicate confidence intervals. The manifest records
run configuration, source revisions and working-tree status, Python/package
versions, solver, units, residence source, and failures. Single LP/simulation
commands with `--output` write `manifest.json` and `result.json`.

This implementation does not add Q-CAST, communication delay or overhead,
probabilistic swap failures, QEC workspaces, fidelity, hardware heralding,
purification protocols, fitted residence-time calibration, or proofs of finite-slot
achievability. Those remain separate extensions. The preserved `D` multiplier is
a resource convention, not a complete purification or QEC protocol.

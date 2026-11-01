# POQI: Path Oblivious Quantum Internet

POQI studies how to distribute entanglement in a quantum network without reserving
an end-to-end path for every request. We build on the path-oblivious entanglement
swapping papers in [`papers/`](papers/), extending their idealized setting of
unlimited memory and no decoherence toward finite quantum memory and finite
entanglement lifetimes.

Our goal is to understand **when proactive, path-oblivious entanglement is more
effective than on-demand, planned-path routing**, and what policies make it useful
under realistic resource constraints.

## Research direction

### Finite memory and decoherence

Extend the rate-based LP formulation with a memory budget `M_x` at each node.
Using Little's law, expected occupancy is the sum, over partners, of pair arrival
rate times mean residence time; this must fit within the node's memory budget.
A decoherence cutoff bounds residence time, but the actual mean depends on how
pairs are consumed, swapped, or evicted. Average occupancy constraints must also
be distinguished from the hard slot limits of a finite-memory network.

The analytical question is how much memory per node is needed to attain a chosen
fraction of the infinite-buffer optimum under otherwise matched assumptions,
and how that requirement scales with network size and demand skew.

### Swapping and storage under scarcity

Treat quantum memory as a cache of entanglement: decide which pairs to admit,
retain, swap, or evict when there are too few slots to serve every partner.
Explore demand-weighted, frequency-based, and age-aware policies alongside the
papers' local balancing rule.

Two refinements of particular interest are discouraging swaps at nodes far from
both endpoints and avoiding swaps between pairs with very different remaining
coherence times. Study whether scarce memory worsens the starvation of
long-distance requests by short-distance requests.

### The crossover hypothesis

We hypothesize that planned-path routing performs better with scarce memory and
short coherence times, while path-oblivious approaches become competitive or
better with ample memory and long coherence times. This is a hypothesis to test,
not an assumed outcome.

The central objective is to map this boundary across memory size, coherence time,
generation rate, and demand pattern, and explain the mechanisms behind it.

## Comparisons and evaluation

Use Q-CAST as a planned-path reference. Its original on-demand model uses  
independent time slots rather than inventory that persists across slots, so a  
comparison must explicitly reconcile that distinction. Evaluate both approaches  
under a common model with the same memory budgets, link and swap success  
probabilities, decoherence rules, and offered request workload; distinguish any  
continuous-inventory adaptation from original Q-CAST.

Measure served requests per unit time, request latency, swaps per served pair,
pairs lost to decoherence, and classical communication overhead. Track unserved
requests and service across distance and demand classes so aggregate throughput
does not hide starvation. In particular, account for the information exchange
needed to maintain pair-count knowledge in path-oblivious policies.

The intended contribution is a resource-aware account of where each approach
works well, supported by analytical bounds and comparable experiments, rather
than a claim that one swapping heuristic is universally best.

## Root implementation

The root-owned `poqi` package implements a prescribed-residence, finite-average-
memory LP and a finite-slot inventory simulator driven by SeQUeNCe's actual event
kernel. Both existing examples remain separate references:
[`path_oblivious`](SeQUeNCe/example/path_oblivious/README.md) preserves the author
implementation, and
[`path_oblivious_corrected`](SeQUeNCe/example/path_oblivious_corrected/README.md)
corrects swap decisions and accounting under unlimited storage. The new package
imports SeQUeNCe itself; production code does not import either example.

Run these commands from the repository root (`E:\POQI`). Python 3.12 is supported
by the local SeQUeNCe checkout. Create a dedicated environment rather than reusing
or copying the environment inside the submodule:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,simulation]"
.\.venv\Scripts\python.exe -m pip install --no-deps -e ./SeQUeNCe
.\.venv\Scripts\python.exe -m poqi sequence-smoke
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp E:/POQI/tmp/root-tests
```

The `simulation` extra installs the dependencies needed by the inventory adapter's
SeQUeNCe imports. Installing the local simulator with `--no-deps` avoids installing
its unrelated notebook application dependencies; broader SeQUeNCe features may
need those additional dependencies. Use a dedicated pytest `--basetemp` directory,
since pytest replaces that directory's contents.

```powershell
.\.venv\Scripts\python.exe -m poqi lp solve --config configs/memory/chain.json
.\.venv\Scripts\python.exe -m poqi lp size-memory --config configs/memory/chain.json --fraction 0.9
.\.venv\Scripts\python.exe -m poqi simulate --backend sequence --config configs/memory/chain.json --output results/memory/chain-simulation
.\.venv\Scripts\python.exe -m poqi experiments memory-sweep --config configs/memory/scaling.json --output results/memory/scaling
```

Output directories must be new. The LP maximizes proportional demand
satisfaction and can size uniform or weighted **mean** memory budgets. The
simulator measures integer slot occupancy, admission blocking, inherited expiry,
per-pair service, and request backlog under an explicit policy. An LP budget does
not prove a hard-slot implementation can attain its target, and prescribed mean
residence times are independent of the optional simulator cutoff.

See [the finite-memory model and usage guide](docs/finite-memory-model.md) for the
equations, configuration schema, policy details, comparison with both earlier
formulations, and interpretation of experimental results.

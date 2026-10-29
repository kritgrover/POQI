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

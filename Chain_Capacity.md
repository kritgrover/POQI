# Hard-slot capacity of chains and what the mean-occupancy LP misses

On the single-repeater workloads below, the memory row of the LP is slack at the measured residence times. At unit generation rates, pressure relaxation delivers $M/(M+1)$ requests per unit time, while the LP predicts one. Generation blocked at a full reservation accounts for the difference.

Under permanent backlog, eager oriented swapping on a chain with nonbinding endpoint memories has the long-run throughput of a finite-buffer tandem line with blocking. At unit link rates, 90% of unlimited-memory throughput requires 9, 13 and 15 slots per repeater for one, two and three repeaters, respectively. These thresholds assume immediate swapping of compatible pairs.

For corrected balancing, the smallest uniform node budgets with positive service are 4, 8 and 12 for one, two and three repeaters, respectively. Guarded pressure relaxation serves at two slots at these lengths. [Model guide](docs/finite-memory-model.md) · [Chain theorem](Saturated_Chain_Theorem.md) · [Lockup extensions](Lockup_Extensions.md)

## The memory row is slack on one repeater

Three-node chain, unit link rates, uniform budget $M$, a request always waiting. The exact rate and mean center occupancy come from the stationary law of the recurrent inventories. Admitted pairs reach the center at twice the service rate, so Little's law gives the residence time an elementary pair actually has. The last column is the LP's answer when given that residence time and budget $M$.

| Policy | $M$ | Exact rate | Mean center occupancy | Share of budget | Implied residence time | LP proportional service |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pressure | 2 | 0.6667 | 0.667 | 33% | 0.50 | 1 |
| Pressure | 4 | 0.8000 | 1.600 | 40% | 1.00 | 1 |
| Pressure | 6 | 0.8571 | 2.571 | 43% | 1.50 | 1 |
| Pressure | 8 | 0.8889 | 3.333 | 42% | 1.88 | 1 |
| Pressure | 12 | 0.9231 | 4.615 | 38% | 2.50 | 1 |
| Pressure | 16 | 0.9412 | 5.765 | 36% | 3.06 | 1 |
| Balancing | 4 | 0.6667 | 2.667 | 67% | 2.00 | 1 |
| Balancing | 8 | 0.8571 | 3.714 | 46% | 2.17 | 1 |
| Balancing | 16 | 0.9333 | 5.733 | 36% | 3.07 | 1 |

Two facts follow.

- **The row is slack and the LP overstates service by exactly the blocking probability.** For pressure relaxation that is $1/(M+1)$. The pairs are lost at a full reservation, which is a boundary event. A constraint on the mean cannot register it.
- **The residence time is not an input.** It grows with the budget, from 0.5 at two slots to 3.06 at sixteen, because a larger buffer lets pairs wait longer for a match. For even $M=2k\ge4$ under pressure relaxation the mean center occupancy is $(k^2+5k-6)/(2k+1)$. A sizing sweep at a fixed residence coefficient therefore answers a different question. At coefficient 1 the LP asks for a mean budget of 1.8 for 90% service, where the chain needs 9 hard slots under pressure relaxation and 11 under balancing.

The LP remains correct as a fluid bound and useful for comparing demand mixes. It does not size hard memory. [Table](scripts/chain_capacity.py) · [Earlier blocking-based sizing](Memory_Sizing_Results.md)

## Arbitrary budgets at one repeater

Let the center reserve $a=\lceil c/2\rceil$ and $b=\lfloor c/2\rfloor$ of its $c$ slots, and let the endpoints have $e_0,e_2\ge2$ slots. Each side can hold at most $A=\min(a,e_0)$ and $B=\min(b,e_2)$ elementary pairs. Under permanent backlog at unit rates the stationary law is uniform on $n$ recurrent imbalance states and the rate is $(n-1)/n$, with

| Policy | Recurrent states $n$ |
| --- | --- |
| Corrected balancing, $a,b\ge2$ | $A+B-1$ |
| Guarded pressure, $a=1$ or $b=1$ | $A+B+1$ |
| Guarded pressure, $a,b\ge2$ | $A+B+1-[A<a]-[B<b]$ |

The bracket is one when the condition holds. A side whose reservation the endpoint cannot fill behaves like balancing there. The rule matched the simulator-backed enumerator on 720 policy/layout combinations with endpoint budgets 2 through 7 and center budgets 2 through 12. One-slot endpoints can stall entirely.

This makes the earlier reversal exact. With two-slot endpoints, a four-slot center gives $n=5$ and rate $4/5$. A six-slot center reserves three per side, which neither endpoint can fill, so $n=3$ and the rate falls to $2/3$. Added repeater memory helps only up to what the neighbors can supply. [Stress tests](Stress_Testing.md#2-change-only-the-repeaters-slots)

The original pressure policy is excluded here. With small endpoints it can reverse a fresh end-to-end pair before the waiting request consumes it, because swaps settle before service.

## Several repeaters form a tandem line

Number the nodes $0,\dots,n$ and let link $i$ join nodes $i-1$ and $i$. Under the orientation rule every stored pair joins some $p<q$, sits in a right-facing slot at $p$ and a left-facing slot at $q$, and covers links $p+1,\dots,q$. Let $x_i$ count the stored pairs covering link $i$.

- A generation on link $i$ raises $x_i$ by one.
- A swap changes no $x_i$.
- A completed end-to-end pair lowers every $x_i$ by one.

Let repeater $i$ reserve $a_i\ge1$ slots to the left and $b_i\ge1$ to the right, with $M_i=a_i+b_i$. Suppose every repeater swaps whenever it holds both a pair ending there and a pair starting there. In settled inventory it holds only one kind. The difference $d_i=x_i-x_{i+1}$ counts pairs ending there when positive and pairs starting there when negative. At an interior link $i$, generation requires $d_i<a_i$ and $d_{i-1}>-b_{i-1}$. These inequalities express availability in the two required reservations. Admission raises $d_i$ and lowers $d_{i-1}$. End-to-end completions preserve every $d_i$.

Put $q_i=d_i+b_i\in\{0,\ldots,M_i\}$. An empty physical chain starts with $q_i=b_i$. An accepted generation on link 1 adds a unit to station 1. On an interior link it moves one unit from the station on its left to the station on its right whenever the source is nonempty and the destination has room. An accepted generation on the final link removes one unit from the last station. With independent Poisson generation attempts these are the transitions of a finite-buffer tandem line with loss at the entrance and blocking between stations.

**Endpoint condition.** Let $B=\sum_{i=1}^{n-1} M_i$. In settled inventory every qubit at an end node has a partner at a repeater, because a waiting request consumes every end-to-end pair immediately. Thus each endpoint holds at most $B$ qubits before the next generation. Giving each endpoint $B+1$ slots guarantees its admission test succeeds whenever the neighboring repeater can admit. This is a sufficient bound.

**Throughput identity.** Let $D_n(t)$ count line departures and $C(t)$ completed requests. A departure is an admitted generation on the last physical link. Only these generations and end-to-end completions change the count $x_n$ of stored pairs spanning that link. Therefore
$$
D_n(t)-C(t)=x_n(t)-x_n(0).
$$
The right-hand side is bounded by $B$ at settled event times. The finite irreducible tandem chain with positive rates has a long-run departure rate. Dividing the identity by $t$ gives the same long-run completion rate. The two counts can differ even at the first event. A generation on the final link of an empty chain causes a line departure and leaves one elementary pair waiting for a match.

**What was checked.**

| Comparison | Result |
| --- | --- |
| Eager oriented swapping, nonbinding end nodes | All 14 rate comparisons agreed across 3–6 links, repeater budgets 2–6 and equal or unequal positive rates. Ten used exact fractions. Four used floating-point stationary laws with absolute tolerance $10^{-10}$. [Case inputs and rates](evidence/theory/tandem.json) |
| Eager oriented swapping, uniform budgets | One repeater gives the same rate. Tests at two repeaters found equality with even budgets and a shortfall at three slots. |
| Repository's guarded pressure policy | At two slots with one reservation per side, the second input puts the pivot under pressure. The guarded-policy comparison at larger budgets is numerical. The largest shortfall in the uniform-budget enumerations was about 0.023. |

"Eager" is an experimental variant in the search script that drops the count thresholds. It is not a production policy. The guarded pressure policy holds back some swaps that eager swapping would make, which costs it up to 0.023 in rate. [Equivalence checks](scripts/chain_tandem_check.py) · [Tests](tests/test_chain_tandem_check.py)

Rates at unit link rates and uniform budgets. The middle value is the root simulator under the guarded pressure policy, a mean over four seeds. The last is the product of one-repeater factors $\bigl(M/(M+1)\bigr)^{n-1}$.

| Links | $M$ | Tandem line | Simulated guarded policy | Product of factors |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 2 | 0.578 | 0.575 | 0.444 |
| 3 | 4 | 0.736 | 0.728 | 0.640 |
| 3 | 8 | 0.849 | 0.840 | 0.790 |
| 3 | 12 | 0.895 | 0.890 | 0.852 |
| 4 | 2 | 0.536 | 0.539 | 0.296 |
| 4 | 4 | 0.704 | 0.704 | 0.512 |
| 4 | 8 | 0.828 | 0.822 | 0.702 |
| 5 | 2 | 0.512 | 0.515 | 0.198 |
| 5 | 4 | 0.684 | 0.687 | 0.410 |
| 5 | 8 | 0.815 | 0.812 | 0.624 |

The simulated column has seed-to-seed variation of roughly 0.007. In these cells the product approximation understates throughput. The rate calculations above allow blocking at neighboring repeaters to depend on the same generation event.

## Memory against chain length

Smallest uniform budget per repeater at which the tandem line reaches a fraction of the unlimited-memory rate.

| Target | 1 repeater | 2 repeaters | 3 repeaters | 4 repeaters |
| ---: | ---: | ---: | ---: | ---: |
| 80% | 4 | 6 | 7 | 8 |
| 90% | 9 | 13 | 15 | not computed |
| 95% | 19 | 27 | 32 | not computed |

The tabulated thresholds apply to eager oriented swapping with nonbinding endpoint memories, equal generation rates, permanent backlog, perfect swaps and no expiry. The table covers up to four repeaters. A general scaling law for growing chain length remains open.

## Minimum observed budget for balancing

Exact enumeration of saturated inventories gives the smallest uniform budget with positive service.

| Links | Corrected balancing | Guarded pressure |
| ---: | ---: | ---: |
| 2 | 4 | 2 |
| 3 | 8 | 2 |
| 4 | 12 | 2 |

Balancing holds a spare pair on every input before it swaps, and a longer chain stacks those reserves. At 12 slots on four links it serves 0.727 per unit time against 0.879 for the tandem line. The simulations agree: balancing completed nothing on five links at any budget up to 12. The pattern $4(n-1)$ is observed for these three lengths and not proved.

## What this means for the LP

- **Saturated chain throughput.** For eager oriented swapping with nonbinding endpoints, the tandem calculation gives the achievable rate directly. In the enumerated uniform-budget comparisons, differences for the guarded pressure policy were at most 0.023. Using this single-demand result in a multi-demand LP would require a joint feasible-rate region.
- **Elsewhere it is open.** A hub that matches several neighbors, or a cycle with two routes, is not a line. The independent-node shortcut is ruled out by the table above. A closure has to carry the dependence between neighboring reservations.
- **The LP's present role is a fluid bound.** Its memory row should not be read as hard slots, and a prescribed residence time should not be read as a property of the network.

## Limits

- Permanent backlog, no expiry, perfect swaps and one end-to-end demand class throughout.
- The tandem derivation assumes eager swapping and end nodes that never fill. For the guarded pressure policy the match is numerical.
- Classical tandem queues already have exact and approximate analytical methods. Downstream capacity and the precise blocking rule matter when transferring results. The derivation above identifies the transition rates of this eager inventory policy. Dai and Towsley’s finite-memory repeater analysis uses a nesting hierarchy with memory assigned per level. Establishing priority for the specific inventory-to-tandem mapping would require a broader comparison. [Exponential tandem queues with blocking](https://doi.org/10.1137/0601013) · [Dai and Towsley](https://arxiv.org/abs/2111.10994)
- Sizing entries marked "not computed" exceed the state limit of the solver used here.

## Reproduce

Run these commands from the repository root with the environment in the README. The capacity script checks 720 policy/layout combinations.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.theory_evidence --output evidence/theory
.\.venv\Scripts\python.exe -B scripts/chain_tandem_check.py
.\.venv\Scripts\python.exe -B scripts/chain_capacity.py
.\.venv\Scripts\python.exe -B scripts/saturated_long_chain_sim.py --output results/memory/long-chains-rerun.json
```

[Capacity report](evidence/prior/lockup-generalization-01/chain-capacity.json) · [Long-chain simulations](evidence/prior/lockup-generalization-01/saturated-long-chains.json) · [Tandem verification manifest](evidence/theory/manifest.json)

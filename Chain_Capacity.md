# Hard-slot capacity of chains and what the mean-occupancy LP misses

The memory row of the LP never binds at the residence times a chain actually produces. On one repeater under pressure relaxation the mean occupancy stays at or below 43% of the budget at every tested budget from 2 to 16, so the LP returns full service while the exact rate is $M/(M+1)$. The LP is a valid upper bound that cannot see blocking, and blocking is the whole loss.

For chains the missing piece has an exact form. Under permanent backlog, swapping as soon as possible with the orientation rule turns a chain of $n$ links into a tandem line of $n-1$ exponential servers with finite buffers and blocking. The repository's guarded pressure policy stays within 0.023 below that line in every case tested. Multiplying one-repeater factors, as an independent-node approximation would, is far too pessimistic. The line also answers how memory must grow with chain length: 9, 13 and 15 slots per repeater for 90% of the unlimited rate at one, two and three repeaters.

Corrected balancing needs four slots per repeater before it serves at all: 4, 8 and 12 slots at one, two and three repeaters. Pressure relaxation needs 2 at every length tested. [Model guide](docs/finite-memory-model.md) · [Chain theorem](Saturated_Chain_Theorem.md) · [Lockup extensions](Lockup_Extensions.md)

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

The bracket is one when the condition holds. A side whose reservation the endpoint cannot fill never comes under pressure from that side, and behaves like balancing there. The rule matched the simulator-backed enumerator on all 720 layouts with endpoint budgets 2 to 7 and center budgets up to 12. It fails for one-slot endpoints, which can stall entirely.

This makes the earlier reversal exact. With two-slot endpoints, a four-slot center gives $n=5$ and rate $4/5$. A six-slot center reserves three per side, which neither endpoint can fill, so $n=3$ and the rate falls to $2/3$. Added repeater memory helps only up to what the neighbors can supply. [Stress tests](Stress_Testing.md#2-change-only-the-repeaters-slots)

The original pressure policy is excluded here. With small endpoints it can reverse a fresh end-to-end pair before the waiting request consumes it, because swaps settle before service.

## Several repeaters form a tandem line

Number the nodes $0,\dots,n$ and let link $i$ join nodes $i-1$ and $i$. Under the orientation rule every stored pair joins some $p<q$, sits in a right-facing slot at $p$ and a left-facing slot at $q$, and covers links $p+1,\dots,q$. Let $x_i$ count the stored pairs covering link $i$.

- A generation on link $i$ raises $x_i$ by one.
- A swap changes no $x_i$.
- A completed end-to-end pair lowers every $x_i$ by one.

Suppose each repeater swaps whenever it holds a pair ending there and a pair starting there. Then repeater $i$ holds only one kind, and $d_i=x_i-x_{i+1}$ counts the pairs ending there when positive and those starting there when negative. A generation on link $i$ needs a free left-facing slot at node $i$ and a free right-facing slot at node $i-1$, that is $d_i<a_i$ and $d_{i-1}>-b_{i-1}$. It then raises $d_i$ and lowers $d_{i-1}$. Completions leave every $d_i$ unchanged.

Put $q_i=d_i+b_i\in\{0,\dots,M_i\}$. Link 1 adds a unit to station 1 and is lost when it is full. Link $i$ moves a unit from station $i-1$ to station $i$, and is blocked when the source is empty or the destination is full. Link $n$ removes a unit from the last station, and each removal is one completed request. This is a tandem line of $n-1$ exponential servers with buffers $M_i$, loss at the entrance and blocking between stages. The end nodes must have enough slots never to bind, since node 0 holds one qubit of every pair covering link 1. One repeater is the single queue with $M+1$ states, which is the chain theorem.

**What was checked.**

| Comparison | Result |
| --- | --- |
| Eager oriented swapping, end nodes with ample memory | Equal to the line in 14 of 14 cases: 3 to 6 links, budgets 2 to 6, equal and unequal rates. Exact rational arithmetic up to 80 states. |
| Eager oriented swapping, uniform budgets | Equal for one repeater, and for two repeaters at even budgets. Otherwise the end nodes bind and the chain is slightly slower. |
| Repository's guarded pressure policy | Equal at two slots when the end nodes have ample memory, for 3 to 6 links. Below the line at larger budgets, by at most 0.023 in the cases tested. |

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

The simulated column has seed-to-seed noise of roughly 0.007, which is why it sits slightly above the line in three rows. Blocking at neighboring repeaters is strongly dependent, so the loss grows far more slowly with length than a product suggests. An Erlang-style fixed point that treats nodes as independent would inherit the product's error. Tandem lines with blocking have no closed form beyond one station, but they are a classical model with exact numerical solutions and established decomposition methods.

## Memory against chain length

Smallest uniform budget per repeater at which the tandem line reaches a fraction of the unlimited-memory rate.

| Target | 1 repeater | 2 repeaters | 3 repeaters | 4 repeaters |
| ---: | ---: | ---: | ---: | ---: |
| 80% | 4 | 6 | 7 | 8 |
| 90% | 9 | 13 | 15 | not computed |
| 95% | 19 | 27 | 32 | not computed |

The requirement grows with length, and more slowly at each step. This is the first quantitative answer in the project to how memory must scale with network size. It holds for chains, eager oriented swapping, permanent backlog, no expiry and perfect swaps.

## Balancing needs four slots per repeater

Exact enumeration of saturated inventories gives the smallest uniform budget with positive service.

| Links | Corrected balancing | Guarded pressure |
| ---: | ---: | ---: |
| 2 | 4 | 2 |
| 3 | 8 | 2 |
| 4 | 12 | 2 |

Balancing holds a spare pair on every input before it swaps, and a longer chain stacks those reserves. At 12 slots on four links it serves 0.727 per unit time against 0.879 for the tandem line. The simulations agree: balancing completed nothing on five links at any budget up to 12. The pattern $4(n-1)$ is observed for these three lengths and not proved.

## What this means for the LP

- **On a chain the closure is the tandem line.** Replacing the generation bound $g\le\gamma$ by the line's throughput reproduces hard-slot service for eager oriented swapping, and is within 0.023 for the guarded pressure policy in the cases tested.
- **Elsewhere it is open.** A hub that matches several neighbors, or a cycle with two routes, is not a line. The independent-node shortcut is ruled out by the table above. A closure has to carry the dependence between neighboring reservations.
- **The LP's present role is a fluid bound.** Its memory row should not be read as hard slots, and a prescribed residence time should not be read as a property of the network.

## Limits

- Permanent backlog, no expiry, perfect swaps and one end-to-end demand class throughout.
- The tandem derivation assumes eager swapping and end nodes that never fill. For the guarded pressure policy the match is numerical.
- We have not searched the literature for this equivalence. Finite-buffer repeater chains have been analysed for nested swapping by Dai and Towsley, with a product formula over nesting levels and memory assigned per level. That is a different protocol and memory model. The classical references on tandem lines with blocking still need to be read for results that transfer.
- Sizing entries marked "not computed" exceed the state limit of the solver used here.

## Reproduce

From the repository root, with the environment in the README. The capacity script takes several minutes because it enumerates 720 layouts through the simulator.

```powershell
.\.venv\Scripts\python.exe -B scripts/chain_tandem_check.py
.\.venv\Scripts\python.exe -B scripts/chain_capacity.py
.\.venv\Scripts\python.exe -B scripts/saturated_long_chain_sim.py --output results/memory/long-chains-rerun.json
```

[Capacity report](results/memory/lockup-generalization-01/chain-capacity.json) · [Long-chain simulations](results/memory/lockup-generalization-01/saturated-long-chains.json)

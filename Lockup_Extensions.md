# Where lockup occurs, what stops it, and what it costs

The two-slot lockup is one case of a wider failure. A stored pair that no pending request can consume and no swap can extend holds its slots forever. On the three-node chain this needs a two-slot endpoint facing a one-slot reservation, so uniform budgets of three or more are safe. On longer chains the original pressure policy locks at larger budgets, and it does so even with a request always waiting. The orientation rule removes the lockup on every chain we enumerated. It does not remove it on the diamond, where a different published condition does. On five- and six-node cycles with one or two demand pairs, no swap condition we tried removes it.

A cutoff turns each lockup into an outage of almost exactly one cutoff. For long cutoffs the original two-slot chain spends all of its spare capacity in outages, and the mean request delay approaches half the cutoff. The guarded chain's delay does not depend on the cutoff.

With swap success probability $q$ the threshold of the lockup theorem moves from $\mu_2$ to $q\mu_2$, and the lock probability keeps a closed form. [Unguarded theorem](Saturated_Chain_Theorem.md#offered-demand-at-two-slots) · [Guarded theorem](Guarded_Chain_Theorem.md)

## How the cases were decided

Without expiry the swap policy never reads the clock. Every inventory reachable from empty can therefore be listed by applying each possible next event and letting the policy settle. The search reuses the repository's settling, pressure, orientation and inventory code unchanged, and only replaces the event timing. It tracks which physical slot each qubit occupies and the order of pairs in each buffer, because the policy consumes the oldest pair first. Request backlogs are capped at "three or more" with every consistent successor explored, so the reachable set is exact.

A closed set of states in which some demand class is never served is a structural lockup. If no class is served it is a dead class. A single inventory that no event changes is frozen. The search agrees with the public simulator on random event words, and its copy of the settling loop agrees with the original on every explored state. [Search and self-checks](scripts/dead_state_search.py) · [Tests](tests/test_dead_state_search.py)

Three experimental filters exist only in this script. None is a production policy.

- **No shortcut.** A swap may not create a pair between two physical neighbors. This is the condition of Iñesta and Wehner (2023).
- **Geodesic.** The pivot must lie on a shortest physical path between the two new endpoints. This implies the no-shortcut condition.
- **Eager.** Count thresholds are dropped and every permitted swap is taken at once. It is used in the [capacity note](Chain_Capacity.md).

## Three-node chain at other budgets

| Budgets (endpoint, center, endpoint) | Original pressure | Orientation guard |
| --- | --- | --- |
| 2, 2, 2 | Frozen inventories reachable from every state | No lockup |
| 2, 3, 2 | Frozen inventories reachable from every state | No lockup |
| Uniform 3 through 14 | No lockup | No lockup |
| 2, 4, 2 and 3, 2, 3 | No lockup | No lockup |
| 1, 4, 1 | Zero service | Zero service |

The backward swap needs pressure at an endpoint. An endpoint is under pressure only when it is full, and a cached end-to-end pair plus one elementary pair fill it only if it has two slots. The wrong-origin pair then freezes the chain only if the reservation it occupies has a single slot. A scan over equal endpoint budgets 1 to 5 and center budgets 2 to 8 found this lockup at exactly those two layouts.

Uniform budgets from 3 to 14 were each enumerated in full. Backward swaps still occur there and waste pairs, but every reachable state can serve again. A proof for all larger budgets is open.

The last row is a different failure, shared by both policies. One-slot endpoints can supply one pair per side. A center with four slots reserves two per side, so no reservation ever fills, pressure never arises, and the balancing threshold of two pairs per side is never met. Center budgets 2 and 3 serve normally with the same endpoints. [Effective buffers for arbitrary budgets](Chain_Capacity.md#arbitrary-budgets-at-one-repeater)

## Longer chains

With two or more repeaters the original policy locks at larger budgets. An intermediate pair that is not yet end-to-end can sit idle even when a request is waiting, so permanent backlog no longer protects it.

| Links | Original pressure locks at | Orientation guard |
| ---: | --- | --- |
| 2 | 2 slots | No lockup at 2 to 14 |
| 3 | 2 and 3 slots | No lockup at 2, 3, 4 |
| 4 | 2 and 3 slots (4 not enumerated) | No lockup at 2, 3 |
| 5 | 4 slots (other budgets not enumerated) | No lockup at 4 |

Saturated service in the root simulator shows the cost at budgets where the original policy does not lock. Entries are completions per unit time at unit link rates, original then guarded, with a request always waiting. Each is a mean over four seeds on the window $[500, 3000)$.

| Links | 2 slots | 3 slots | 4 slots | 6 slots | 8 slots | 12 slots |
| ---: | --- | --- | --- | --- | --- | --- |
| 2 | .659 / .659 | .743 / .743 | .794 / .794 | .853 / .853 | .886 / .886 | .922 / .922 |
| 3 | 0 / .575 | 0 / .667 | .660 / .728 | .758 / .798 | .825 / .840 | .885 / .890 |
| 4 | 0 / .539 | 0 / .629 | .534 / .704 | .667 / .779 | .768 / .822 | .852 / .874 |
| 5 | 0 / .515 | 0 / .601 | .022 / .687 | .563 / .765 | .687 / .812 | .815 / .865 |

On one repeater the two policies coincide under backlog, as the guarded theorem states. On five links at six slots the original policy delivers 26% less. [Simulation](scripts/saturated_long_chain_sim.py)

## The diamond

The search finds exactly two frozen inventories on the two-qubit diamond. One holds two 0–2 pairs and one 1–3 pair, and the other is its mirror. These are the pair types and counts recorded in all ten archived frozen runs. The search also finds a third closed class that keeps serving 0–1 while 0–3 and 1–2 starve, which is what the two unfrozen seeds of the later cohort did. [Archived runs](QCAST_Concurrent_Results.md#persistent-poqi-can-fill-memory-with-pairs-that-no-request-can-release) · [Guard comparison](Guarded_Diamond_Results.md)

The mechanism is the chain's, routed around the cycle.

1. Node 1 swaps elementary pairs 0–1 and 1–3 into a 0–3 pair. No 0–3 request is waiting, so it is cached.
2. A 2–3 pair is generated. Node 3 now holds a pair in each of its two slots and is under pressure. It swaps the cached 0–3 pair with the 2–3 pair.
3. The result is a 0–2 pair. Nodes 0 and 2 are physical neighbors, but this pair sits in node 0's slot for neighbor 1 and node 2's slot for neighbor 3.
4. An elementary 0–2 pair and an elementary 1–3 pair complete the freeze. Every edge is blocked, every node has one partner, and no demand class matches a stored pair.

In step 2 node 3 uses two qubits generated toward different neighbors, so the orientation rule permits the swap. That is why the guard changes nothing on this diamond. The no-shortcut condition forbids the swap, because its output joins physical neighbors, and with it the search finds no lockup.

## No single swap condition is enough

Each cell reports whether a class that starves some demand is reachable. "Lock" means it is. Uniform budgets, no expiry, pressure relaxation with the stated condition added.

| Network and demand pairs | Slots | None | Orientation | No shortcut | Both | Geodesic |
| --- | --- | --- | --- | --- | --- | --- |
| Chain, 3 nodes, 0–2 | 2 | Lock | – | – | – | – |
| Chain, 4 nodes, 0–3 | 2, 3 | Lock | – | Lock | – | – |
| Chain, 5 nodes, 0–4 | 2, 3 | Lock | – | Lock | – | – |
| Chain, 5 nodes, 0–4 and 1–3 | 2, 3 | Lock | – | Lock | – | – |
| Chain, 6 nodes, 0–5 | 4 | Lock | – | Lock | – | – |
| Diamond, 0–3, 0–1, 1–2 | 2 | Lock | Lock | – | – | – |
| Diamond, 0–3, 1–2 | 2, 3 | Lock | Lock | – | – | – |
| Star, 3 leaves, all leaf pairs | 3, 4 | – | – | – | – | – |
| 5-cycle, 0–2 | 2, 3 | Lock | Lock | Lock | Lock | Lock |
| 5-cycle, 0–2 | 4 | – | – | Lock | Lock | – |
| 5-cycle, 0–2 and 1–3 | 2 | Lock | Lock | Lock | Lock | Lock |
| 5-cycle, 0–2 and 1–3 | 5 | – | Lock | – | – | – |
| 6-cycle, 0–3 | 2, 3 | Lock | Lock | Lock | Lock | Lock |
| 6-cycle, 0–3 and 1–4 | 2 | Lock | Lock | Lock | Lock | Lock |

Budgets at which every rule was free of lockup are omitted: the three-node chain at 3 and 4, the four-node chain at 4, both diamonds at 4, and the first diamond at 3. The five-slot row used a backlog cap of two.

Three observations follow.

- **Each published condition fails somewhere.** Orientation fails on the diamond, and on the 5-cycle it is the only rule that still locks at five slots. The no-shortcut condition fails on every chain with two or more repeaters, because an endpoint can still reverse a long pair into a shorter one that is not a physical edge.
- **A restriction can create a lockup.** On the 5-cycle at four slots the unrestricted policy has none, and adding the no-shortcut filter introduces one. Forbidding a swap also removes an escape.
- **Sparse demand on a cycle defeats all of them at small budgets.** Path-oblivious swapping makes pairs that nobody requested. A frozen 5-cycle inventory under both conditions holds elementary pairs 0–1, 0–4 and 2–3 and a 1–4 pair built the long way round through nodes 2 and 3. That pair fills node 1's slot toward 2 and node 4's slot toward 3, so the two links needed for a 0–2 pair cannot generate. A single 1–4 request would release it.

A frozen inventory always consists of pair types outside the demand support. If every pair type had positive demand, requests alone could empty any inventory. The lockup is therefore a property of hard slots, no expiry and demand that covers only some pairs. Local swap conditions reduce it. On general topologies they do not remove it, so some form of expiry or eviction is required, and its cost is the subject of the next section.

## With a cutoff the lockup becomes an outage

Give every pair a lifetime $T$ from generation. A swap output inherits the earliest deadline of its inputs. Consider the two-slot chain under the original policy.

**Proposition.** Suppose an endpoint swap creates a wrong-origin pair at time $s$, and its oldest elementary ancestor was generated at time $g$. Then no request completes in $[s, g+T)$, whatever arrives, and the pair expires at $g+T$.

*Proof.* The pair joins the center to one endpoint, say the left, while its center qubit occupies the right reservation, which has one slot. No right generation is admitted while it lives. The left link can add at most one pair, which also joins the center to the left endpoint. Every node then has at most one partner, so no swap is possible, and an end-to-end pair can only come from a center swap. The pair is not end-to-end, so no request consumes it. Its deadline is the earliest ancestor deadline, $g+T$, and nothing removes it sooner. $\square$

The outage therefore lasts $T-(s-g)$. In 11,982 outages across the runs below, the measured length plus the measured age $s-g$ equaled the cutoff to the simulator tick, and no completion occurred inside any outage. For long cutoffs the mean age should approach $1/(\lambda+\delta)+1/(2\lambda+\delta)$ at equal link rates $\lambda$. This is the wait for the second link given that no request came first, plus the wait for the generation that triggers the endpoint swap. It gives 1.07 and 1.24 at the two loads below. The measured means at cutoff 300 were 0.97 and 1.32, each from about 220 outages.

**Consequences for long cutoffs.** Fix a request rate $\delta<\mu_2$. During an outage about $\delta T$ requests accumulate. They drain at net rate $\mu_2-\delta$, and while they drain the queue is never empty, so no pair sits idle and no new outage can start. After the drain the next outage begins within a time that does not grow with $T$. One cycle thus lasts about $T\mu_2/(\mu_2-\delta)$, and

$$
\text{fraction of time in outage}\to 1-\frac{\delta}{\mu_2},\qquad
\frac{\text{mean request delay}}{T}\to\frac12 .
$$

The first limit says the chain spends all of its spare capacity in outages. The second follows from the queue area of one cycle, $\delta T^2\mu_2/(2(\mu_2-\delta))$, divided by the cycle length and by $\delta$. The proposition is proved. These two limits are a renewal argument that we have not written as a full proof.

Simulation at unit link rates, eight seeds per row, original and guarded policy on identical arrivals. The limits are $0.625$ and $0.25$ for the outage fraction at the two loads, and $T/2$ for the delay.

| Cutoff $T$ | Load | Outage fraction | Mean outage | Mean delay, original | Mean delay, guarded |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0.25 | 0.308 | 1.71 | 2.20 | 0.79 |
| 3 | 0.50 | 0.128 | 1.93 | 5.17 | 3.33 |
| 10 | 0.25 | 0.533 | 8.35 | 5.41 | 0.29 |
| 10 | 0.50 | 0.219 | 8.94 | 8.18 | 2.41 |
| 30 | 0.25 | 0.603 | 28.79 | 15.34 | 0.25 |
| 30 | 0.50 | 0.244 | 28.91 | 17.77 | 2.36 |
| 100 | 0.25 | 0.622 | 98.71 | 50.55 | 0.25 |
| 100 | 0.50 | 0.241 | 98.88 | 53.22 | 2.58 |
| 300 | 0.25 | 0.623 | 298.68 | 150.96 | 0.25 |
| 300 | 0.50 | 0.246 | 299.03 | 152.36 | 2.63 |

Both policies served the offered load in every row. The cost of the missing guard is delay, and it grows in proportion to the memory lifetime. A better memory makes the unguarded chain slower. The no-expiry theorem is the limit of this statement. [Runner](scripts/cutoff_outage_analysis.py) · [Summary](results/memory/cutoff-outage-02/summary.json)

## Swap success below one

Let each swap succeed with probability $q$, independently. A failed swap destroys both inputs and produces nothing.

**Saturated rates.** A failed center swap changes the inventory exactly as a success followed by immediate consumption. The imbalance walk is unchanged, and both saturated rates are multiplied by $q$.

**Lockup theorem.** One service is a geometric number of attempts, each lasting the later of two exponential generation times. Write $u,v$ for the link rates, $c=u+v$, $k=c+\delta$ and

$$
\phi(t)=\frac{u}{u+t}+\frac{v}{v+t}-\frac{c}{c+t},\qquad
\phi_q(t)=\frac{q\,\phi(t)}{1-(1-q)\phi(t)} .
$$

The mean service time is $1/(q\mu_2)$. The branching argument of the theorem applies with $\phi_q$ in place of $\phi$. Lockup has probability one if and only if $\delta\le q\mu_2$. Above that, let $z$ be the smallest root of $z=\phi_q(\delta(1-z))$ and $s=\delta(1-z)$. A busy period that starts with one link already stored has a shorter first service, with transform $\psi_r(t)=\frac{r}{r+t}\bigl(q+(1-q)\phi_q(t)\bigr)$ when the missing link has rate $r$. Count one excursion from empty inventory and empty queue as ending at the first failed swap, cleared busy period, consumed cache, wrong-origin pair or endless busy period. Then

$$
h=q^2\,\phi(\delta)\,\frac{c}{k},\qquad
e=\frac{\delta}{k}(1-z)+\frac{u}{k}\frac{\delta}{v+\delta}\bigl(1-\psi_v(s)\bigr)
  +\frac{v}{k}\frac{\delta}{u+\delta}\bigl(1-\psi_u(s)\bigr),\qquad
P=\frac{h}{h+e}.
$$

The factor $q^2$ in $h$ is one successful center swap and one successful backward swap. A failed backward swap destroys the cached pair and returns the chain to empty.

| Swap success | Threshold | $\delta=0.5$ | $\delta=0.75$ | $\delta=1$ |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.6667 | 1 | 0.815271 | 0.485281 |
| 0.9 | 0.6000 | 1 | 0.666847 | 0.390846 |
| 0.5 | 0.3333 | 0.402791 | 0.185582 | 0.108741 |

Unit link rates. An independent first-passage calculation with the queue truncated at 400 brackets every entry, to at least seven digits, for unit rates and for rates $(1,2)$.

**Guarded theorem.** The same proof gives the classification with $m$ replaced by $m/q$. The queue is positive recurrent below $q\mu_2$, null recurrent at it and transient above. We have not written this case out in full.

The root simulator has perfect swaps. These are results about the model with failure, checked by an independent calculation and not by simulation. [Closed form and check](scripts/two_slot_swap_failure.py)

## Limits

- Verdicts are exact for the listed networks, budgets and demand sets, and say nothing about others. Requests are served concurrently per demand pair, which for one demand class is the root simulator's FIFO.
- The diamond experiments used a slotted wrapper with batched generation. The search applies one event at a time. It reproduces their frozen inventories, but the two models need not reach exactly the same sets.
- The absence of lockup at uniform budgets above two on the three-node chain is enumerated up to 14 and not proved in general.
- The two long-cutoff limits rest on a renewal argument and simulation.
- Cutoff and swap-failure results are for the two-slot three-node chain.

## Reproduce

From the repository root, with the environment in the README.

```powershell
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py chain --memory 2 3 4 --all-rules
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py chain --layouts 2,3,2 3,2,3 1,4,1 --all-rules
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py diamond --memory 2 --check
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py cycle5 --memory 2 3 4 --all-rules
.\.venv\Scripts\python.exe -B scripts/saturated_long_chain_sim.py --output results/memory/long-chains-rerun.json
.\.venv\Scripts\python.exe -B scripts/cutoff_outage_analysis.py --output results/memory/cutoff-outage-rerun
.\.venv\Scripts\python.exe -B scripts/two_slot_swap_failure.py
```

Other topologies are listed in `TOPOLOGIES` in the search script. The six-node chain at four slots takes several minutes. [All rule verdicts](results/memory/lockup-generalization-01/rule-scan.jsonl)

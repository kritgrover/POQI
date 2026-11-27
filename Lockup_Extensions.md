# Where lockup occurs, what stops it, and what it costs

The two-slot chain, diamond and sparse-demand cycles have concrete generation sequences that freeze their memories under pressure relaxation. Under the physical-origin guard, the two-slot chain is stable below its saturated rate, while the diamond and both cycles still admit a freeze. On one repeater the finite search found no freeze at uniform budgets 3 through 14. Larger uniform budgets remain open. [Uncapped traces and terminal inventories](evidence/theory/uncapped-freezes.json)

On the two-slot chain, a wrong-origin pair prevents service until its inherited cutoff. At cutoff 300 and unit link rates, the unguarded mean delay measured 151 and 152 time units at loads 0.25 and 0.50. A renewal argument predicts half the cutoff at long lifetimes. For the guarded chain at load 0.25, measured mean delay fell from 0.79 at cutoff 3 to 0.25 at cutoff 300.

With swap success probability $q$ the threshold of the lockup theorem moves from $\mu_2$ to $q\mu_2$, and the lock probability keeps a closed form. [Unguarded theorem](Saturated_Chain_Theorem.md#offered-demand-at-two-slots) · [Guarded theorem](Guarded_Chain_Theorem.md)

## How the cases were decided

The search enumerates a finite graph of inventories and per-demand queue counts. It retains the qubits' physical origins and the order of pairs within each buffer. With oldest-first eviction it also retains the order across buffers. With no expiry and zero or infinite eviction patience, event order determines the transitions. Independent event streams of strictly positive rates give each finite generation/request word positive probability.

**What capping establishes.** Project a concrete queue count $q$ to $\min(q,K)$, where $K=3$ unless indicated. A count below $K$ is known exactly. From a capped count the code tests the smallest possible representative $q=K$ and rejects the enumeration if a single event empties that queue. Otherwise increasing its length leaves a positive queue after draining and preserves both the inventory and number served. For $a$ arrivals and $s$ completions of that class in the event, all possible projected successors lie between $\min(K,K+a-s)$ and $K$, inclusive. The search includes the Cartesian product of these possibilities across classes. Induction on the event word proves that the graph contains every projected concrete path. Two consecutive graph edges can select inconsistent hidden queue lengths. The general reachability and starvation tables below describe closed classes of this finite graph.

**What can be ruled out.** A concrete frozen inventory has no possible service or inventory change under any event. Sending one request class at a time until every count reaches $K$ leaves the same inventory. At that projected state every edge is a self-loop with zero reward, so it must appear as a closed singleton in the search. Therefore a search with no such node rules out an uncapped freeze. Absence of graph classes that starve a demand does not by itself establish queue stability, almost-sure service, or absence of every possible starvation behavior with unbounded queues.

**Positive witnesses.** A closed component with no completion for one class indicates structural starvation in the finite graph. A concrete freeze can be proved separately. Starting empty and issuing only generations, we searched for inventories in which every link is blocked and no stored pair matches any demand. We replayed ten traces through the public simulator with unbounded per-class queues and checked every possible next event from backlog zero and seven per class. Each check preserved all stored pairs, admitted no generation, made no swap and completed no request. These facts extend to any backlog: admission and swap selection read only inventory and the service step has no matching pair to remove. Inducting over subsequent events proves permanence without queue truncation. The certificates include both mirror inventories on the two-slot chain and diamond, and freezes on the five- and six-node cycles under the two production pressure policies. The search script's additional filters have separate finite-graph results. [Uncapped certificates](evidence/theory/uncapped-freezes.json) · [Reproduction manifest](evidence/theory/manifest.json) · [Finite search](scripts/dead_state_search.py)

Three experimental filters exist only in this script. None is a production policy.

- **No shortcut.** A swap may not create a pair between two physical neighbors. This is the condition of Iñesta and Wehner (2023).
- **Geodesic.** The pivot must lie on a shortest physical path between the two new endpoints. This implies the no-shortcut condition.
- **Eager.** Count thresholds are dropped and every permitted swap is taken at once. It is used in the [capacity note](Chain_Capacity.md).

## Three-node chain at other budgets

| Budgets (endpoint, center, endpoint) | Original pressure, finite graph | Orientation guard, finite graph |
| --- | --- | --- |
| 2, 2, 2 | Frozen inventories reachable from every state | No lockup |
| 2, 3, 2 | Frozen inventories reachable from every state | No lockup |
| Uniform 3 through 14 | No lockup | No lockup |
| 2, 4, 2 and 3, 2, 3 | No lockup | No lockup |
| 1, 4, 1 | Zero service | Zero service |

The four-event trap on the two-slot chain uses a full endpoint to swap backward and a single-slot center reservation to retain the resulting wrong-origin pair. With equal endpoint budgets 1–5 and center budgets 2–8, the scan found this type of lockup in the two layouts shown above.

The finite search covered each uniform budget from 3 through 14. Some backward swaps wasted pairs, but the search found no closed starving component at these budgets. This rules out an uncapped frozen inventory there. A proof covering larger uniform budgets remains open.

The last row is a different failure, shared by both policies. One-slot endpoints can supply one pair per side. A center with four slots reserves two per side, so no reservation ever fills, pressure never arises, and the balancing threshold of two pairs per side is never met. Center budgets 2 and 3 serve normally with the same endpoints. [Effective buffers for arbitrary budgets](Chain_Capacity.md#arbitrary-budgets-at-one-repeater)

## Longer chains

With two or more repeaters the original policy locks at larger budgets. An intermediate pair that is not yet end-to-end can sit idle even when a request is waiting, so permanent backlog no longer protects it.

| Links | Original pressure, finite-graph locks | Orientation guard, finite graph |
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

The finite graph has exactly two frozen inventories on the two-qubit diamond. Concrete public replays reach both. One holds two 0–2 pairs and one 1–3 pair, and the other is its mirror. These are the pair types and counts seen in the ten archived frozen runs. A third closed component of the finite graph contains completions for 0–1 alone, consistent with the observed finite-window starvation of the two unfrozen seeds in a later cohort. [Archived runs](QCAST_Concurrent_Results.md#persistent-poqi-can-fill-memory-with-pairs-that-no-request-can-release) · [Guard comparison](Guarded_Diamond_Results.md) · [Concrete traces](evidence/theory/uncapped-freezes.json)

The mechanism is the chain's, routed around the cycle.

1. Node 1 swaps elementary pairs 0–1 and 1–3 into a 0–3 pair. No 0–3 request is waiting, so it is cached.
2. A 2–3 pair is generated. Node 3 now holds a pair in each of its two slots and is under pressure. It swaps the cached 0–3 pair with the 2–3 pair.
3. The result is a 0–2 pair. Nodes 0 and 2 are physical neighbors, but this pair sits in node 0's slot for neighbor 1 and node 2's slot for neighbor 3.
4. An elementary 0–2 pair and an elementary 1–3 pair complete the freeze. Every edge is blocked, every node has one partner, and no demand class matches a stored pair.

In step 2 node 3 uses two qubits generated toward different neighbors, so the orientation rule permits the swap. That is why the guard changes nothing on this diamond. The no-shortcut condition forbids the swap, because its output joins physical neighbors, and with it the search finds no lockup.

## No single swap condition is enough

Each cell reports the finite graph for the stated network, budget and swap rule. “Lock” means a reachable closed component has no completion for at least one demand class. A dash means every closed component contains a completion for every demand class. The uncapped certificates above establish permanence for selected cells.

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

Additional finite-graph cases with no closed starving component under any rule were the three-node chain at 3 and 4, the four-node chain at 4, both diamonds at 4, and the first diamond at 3. The five-slot row used a backlog cap of two.

Three observations follow.

- **Rule effects depend on topology.** The public replay certifies an oriented diamond freeze. In the finite graph, the five-slot 5-cycle has a starving class only with the orientation condition. The no-shortcut graph has a starving class on the tested longer chains, where an endpoint can reverse a long pair into a shorter virtual link.
- **A restriction can remove an escape.** On the four-slot 5-cycle, adding the no-shortcut filter introduced a closed starving component in the finite graph.
- **Sparse demand leaves occupied memory that no request can release.** The finite graph has starving components under all five rules on the two-slot 5- and 6-cycles. An example on the 5-cycle under both conditions holds elementary pairs 0–1, 0–4 and 2–3 and a 1–4 pair built through nodes 2 and 3. That pair fills node 1’s slot toward 2 and node 4’s slot toward 3. A 1–4 request would release it.

A freeze with no possible completion contains only pair types outside the demand support. If every pair type has positive request rate and per-pair service is available, a sequence of requests can empty any finite inventory. The duration of a stall then depends on the arrival rates of requests able to release memory. For the sparse demand studied here, expiry and eviction both offer ways to restore service. [Recovery experiments](Recovery_Baseline.md)

## First release under rare background demand

**Proposition.** Condition on a settled frozen inventory $F$ with no eviction. The original workload has no demand for its stored pair types. Let $J(F)$ be the set of **distinct** stored endpoint pairs. Add independent Poisson background requests at rates $\beta_j$ and serve requests concurrently per pair. Put $\eta_F=\sum_{j\in J(F)}\beta_j$. Without expiry the time $U$ to the first change of inventory is exponential of rate $\eta_F$ when $\eta_F>0$. At $\eta_F=0$ the inventory stays frozen indefinitely.

**Proof.** Before the first request for a type in $J(F)$, every generation remains blocked, swapping remains disabled and every other request simply queues. The first arrival for any type in $J(F)$ consumes a pair at once. At a stopping time when $F$ has been reached, independence of future Poisson increments gives $\Pr(U>t\mid F)=e^{-\eta_Ft}$. An arrival targets an endpoint pair, so two stored copies of that type share one request clock. If each type in $J(F)$ receives rate $\epsilon$, the mean first-release time is $1/(|J(F)|\epsilon)$. For example, the frozen diamond holding two 0–2 pairs and one 1–3 pair has two releasing types.

If the earliest remaining inherited lifetime in $F$ is $r$, the first inventory change occurs at $\min(U,r)$ under the same assumptions. Its mean conditional on the inventory and current deadlines is $(1-e^{-\eta_Fr})/\eta_F$, with value $r$ at $\eta_F=0$. These statements concern the first freed qubit. Service to the original workload can require further generations and swaps. The uncapped checker independently injects one request for each distinct stored type and verifies that it consumes a pair. [Releasing types and traces](evidence/theory/uncapped-freezes.json)

## With a cutoff the lockup becomes an outage

Give every pair a lifetime $T$ from generation. A swap output inherits the earliest deadline of its inputs. Consider the two-slot chain under the original policy.

**Proposition.** Suppose an endpoint swap creates a wrong-origin pair at time $s$, and its oldest elementary ancestor was generated at time $g$. Then no request completes in $[s, g+T)$, whatever arrives, and the pair expires at $g+T$.

*Proof.* The pair joins the center to one endpoint, say the left, while its center qubit occupies the right reservation, which has one slot. No right generation is admitted while it lives. The left link can add at most one pair, which also joins the center to the left endpoint. Every node then has at most one partner, so no swap is possible, and an end-to-end pair can only come from a center swap. The pair is not end-to-end, so no request consumes it. Its deadline is the earliest ancestor deadline, $g+T$, and nothing removes it sooner. $\square$

The outage therefore lasts $T-(s-g)$. In 11,982 outages across the runs below, the measured length plus the measured age $s-g$ equaled the cutoff to the simulator tick, and no completion occurred inside any outage. For long cutoffs the mean age should approach $1/(\lambda+\delta)+1/(2\lambda+\delta)$ at equal link rates $\lambda$. This is the wait for the second link given that no request came first, plus the wait for the generation that triggers the endpoint swap. It gives 1.07 and 1.24 at the two loads below. The measured means at cutoff 300 were 0.97 and 1.32, each from about 220 outages.

**Conjectured long-cutoff limits.** Fix $0<\delta<\mu_2$. An outage of order $T$ accumulates about $\delta T$ requests. The renewal approximation assumes the subsequent busy period drains these requests at net rate $\mu_2-\delta$ and that the time until a new outage after the queue empties is negligible relative to $T$. This gives cycle length approximately $T\mu_2/(\mu_2-\delta)$ and predicts

$$
\text{fraction of time in outage}\to 1-\frac{\delta}{\mu_2},\qquad
\frac{\text{mean request delay}}{T}\to\frac12 .
$$

The first prediction assigns the spare capacity to outages. For the second, the approximate queue area per cycle is $\delta T^2\mu_2/(2(\mu_2-\delta))$. Dividing by cycle length and by $\delta$ gives $T/2$. Establishing these limits requires control of the residual outage length, recovery time and queue-area moments as $T$ increases. The finite-cutoff no-service proposition above is proved.

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

Both policies served approximately the offered load over these finite windows. Under the original policy, measured mean delay grew from 2.20 to 150.96 at load 0.25 and from 5.17 to 152.36 at load 0.50 as the cutoff increased from 3 to 300. [Runner](scripts/cutoff_outage_analysis.py) · [Observed results](evidence/prior/cutoff-outage-02/summary.json)

## Swap success below one

Let each swap succeed independently with probability $0<q\le1$. A failed swap destroys both inputs and produces nothing.

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

- Closed-component verdicts are exact for the finite queue abstraction, stated topology, budget, rules and demand support. The uncapped certificates establish frozen inventories on the specific instances replayed. Requests are served concurrently per demand pair.
- The diamond experiments used a slotted wrapper with batched generation. The search applies one event at a time. It reproduces their frozen inventories, but the two models need not reach exactly the same sets.
- Frozen inventories are ruled out on the three-node chain at uniform budgets 3 through 14 by the finite search. Larger uniform budgets remain open.
- The two long-cutoff limits rest on a renewal argument and simulation.
- Cutoff and swap-failure results are for the two-slot three-node chain.

## Reproduce

From the repository root, with the environment in the README.

```powershell
.\.venv\Scripts\python.exe -B -m scripts.theory_evidence --output evidence/theory
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py chain --memory 2 3 4 --all-rules
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py chain --layouts 2,3,2 3,2,3 1,4,1 --all-rules
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py diamond --memory 2 --check
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py cycle5 --memory 2 3 4 --all-rules
.\.venv\Scripts\python.exe -B scripts/saturated_long_chain_sim.py --output results/memory/long-chains-rerun.json
.\.venv\Scripts\python.exe -B scripts/cutoff_outage_analysis.py --output results/memory/cutoff-outage-rerun
.\.venv\Scripts\python.exe -B scripts/two_slot_swap_failure.py
```

Other topologies are listed in `TOPOLOGIES` in the search script. The six-node chain at four slots takes several minutes. [Rule scan](evidence/prior/lockup-generalization-01/rule-scan.jsonl) · [Five-slot supplement](evidence/prior/lockup-generalization-01/rule-scan-five-slots.jsonl)

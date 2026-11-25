# Service and permanent lockup on a finite-memory three-node chain

On a three-node chain with a waiting request for every endpoint pair produced, pressure relaxation at a budget of **two fewer slots per node** attains the same long-run service rate as corrected balancing. The identity holds even when the two links generate at different rates. Its mechanism is a reserve implicit in the balancing predicate. Once the chain starts serving, balancing keeps one elementary pair on each link. Pressure relaxation makes those two center slots available when a link reservation fills.

With **two slots and no expiry**, letting the queue empty changes the outcome. At or below the saturated service rate, the pressure policy eventually loses the ability to serve any request with probability one. Above that rate, it either locks or enters a busy period that lasts forever. The second theorem derives the probability of each outcome from the reservation inherited by a swapped pair. [Offered demand at two slots](#offered-demand-at-two-slots)

## What is recovered and what is new

**Recovered.** The pressure-relaxation rate in the table below is the classical throughput of a two-input matching station with finite buffers. With buffers $K_1$ and $K_2$ it equals $\lambda(K_1+K_2)/(K_1+K_2+1)$ at equal rates, follows a truncated geometric law otherwise, and depends on the buffers only through their sum. The same expression is already available for quantum repeaters and switches.

- Krishnamurthy, Suri and Vernon print both rate cases as equations (1.4) and (1.1), crediting earlier work on stochastic assembly systems. [§3.1](https://pages.cs.wisc.edu/~vernon/papers/poems.03buzacott.pdf#page=9)
- Vardoyan, Guha, Nain and Towsley give the finite-buffer stationary law and capacity of an entanglement switch with $k$ heterogeneous links and $B$ qubits per link. Evaluating their expression at two links gives this chain's law for even $M=2B$. They do not write that case, and their homogeneous analysis continues with $k\ge3$ after noting that two links with unbounded buffers have no stationary distribution. [§IV-A2, arXiv:1903.04420](https://arxiv.org/abs/1903.04420) · [Journal version](https://people.cs.umass.edu/~gvardoyan/Pubs/TQE3058058_final.pdf)
- Dai and Towsley give $\lambda q^k\prod_{i<k}2B_i/(2B_i+1)$ for nested swapping on a chain of $2^k$ links with $B_i$ memories per side at level $i$ and swap success probability $q$. It is exact in a limit and used as an approximation elsewhere. One repeater gives $\lambda q\,2B_0/(2B_0+1)$. [Theorem 1, arXiv:2111.10994](https://arxiv.org/abs/2111.10994)
- Mai, La, Battou, Amlou and Nunn analyse the same three-node chain as a double-ended queue with memory capacities $K_0$ and $K_1$, unequal and possibly state-dependent rates, swap failure and maximum holding times. With constant rates, no holding limit and negligible swap and reset delays, their Corollary 1 reduces to the pressure row. They do not write that special case. [Eq. (12), arXiv:2608.11429](https://arxiv.org/abs/2608.11429)

The two-slot rate $\mu_2$ in the second theorem is also known. It is the reciprocal of the mean of the later of two independent exponential generation times. At equal rates this is the familiar $2\lambda/3$. [Coopmans, Brand and Elkouss, Proposition 3](https://arxiv.org/abs/2103.11454) · [Mai et al., text following Eq. (7)](https://arxiv.org/abs/2608.11429)

We rederive these rates because the proof has to establish which buffer sizes the two swap predicates realize in the simulator. They also check its transitions.

**New.** Two statements are absent from the works above. A search of the literature on assembly-like and double-ended queues in November 2026 found no counterpart either.

1. *Balancing costs two slots.* The max-min balancing predicate keeps one elementary pair in reserve on each link. Its saturated rate at budget $M$ equals the pressure rate at $M-2$, and it is zero below four slots.
2. *Permanent lockup under offered demand.* With two slots and no expiry, an idle end-to-end pair can be swapped backward, after which the chain freezes. This happens with probability one at or below $\mu_2$, and with an explicitly computed probability strictly between zero and one above it. Lighter demand makes permanent failure more likely. [Which swap rules admit the trap](#which-swap-rules-admit-the-trap)

## Model and theorem

The [guarded-chain follow-up](Guarded_Chain_Theorem.md) proves that checking
the local physical origin of each swap input preserves this saturated service
and restores stability for every strictly subcritical offered rate at two slots.

The physical links are left–center and center–right. Start empty. Each node has the same finite integer memory budget $M$. The center reserves $a=\lceil M/2\rceil$ slots on one link and $b=\lfloor M/2\rfloor$ on the other. Label the former link left. Independent Poisson processes offer individual successful generation events at rates $\lambda_L,\lambda_R>0$ per unit time. Hardware rejects an event if its endpoint slots or its link reservations are full. Each swap uses one pair on each incident link and succeeds with certainty. There is no expiry. After every event, the simulator settles all eligible swaps at all nodes, then immediately consumes any end-to-end pair. Only endpoint-to-endpoint requests are present and one is always waiting. This is the continuous-time saturated benchmark for the repository's reserved admission and swap predicates. [Admission and quotas](src/poqi/simulation/inventory.py) · [Settling, pressure and service order](src/poqi/simulation/sequence_adapter.py)

Let $C(t)$ be the number of completed requests by time $t$. From an empty start, $C(t)/t$ converges almost surely to a rate $\mu$. In the positive-service cases the difference $d=l-r$ between the two settled elementary pair counts follows a reflecting birth–death chain in its recurrent class.

| Policy | Positive-service budgets | Recurrent interval for $d$ | Rate at $\lambda_L=\lambda_R=\lambda$ |
| --- | --- | --- | --- |
| Pressure relaxation | $M\ge2$ | $[-b,a]$ | $\lambda M/(M+1)$ |
| Corrected balancing | $M\ge4$ | $[1-b,a-1]$ | $\lambda(M-2)/(M-1)$ |

The pressure row is the known finite-buffer rate with buffers $a$ and $b$. The balancing row, and the smallest budget at which each policy serves, are specific to these swap predicates. At every smaller nonnegative budget the corresponding policy has zero service. For unequal rates let $[L,U]$ denote the applicable interval, $n=U-L+1$, and $\rho=\lambda_L/\lambda_R$. Its stationary probabilities and service rate are

$$
\pi_{L+j}=\frac{\rho^j}{\sum_{k=0}^{n-1}\rho^k},\qquad
\mu=\lambda_L(1-\pi_U)=\lambda_R(1-\pi_L).
$$

For any $M\ge4$, balancing at $M$ and pressure relaxation at $M-2$ have the same interval, and hence the same service rate. This compares two **uniform** budgets. Other allocations with fewer slots at just one node require checking that endpoint constraints still permit the same transitions.

## Proof

**1. One generation event can produce at most one swap and one completion.** Observe inventory after service. From an empty start, the end-to-end buffer is empty at each such observation. Write the direct link counts as $(l,r)$. For both policies, a settled state has $\min(l,r)\le1$ because two available pairs on each side would permit a balancing swap toward the empty output. For pressure relaxation, a settled state with two positive inputs also has $l<a$ and $r<b$. Otherwise the occupied full quota would trigger the relaxed predicate at the center.

A single accepted generation raises one count by one. Before any center swap, neither endpoint has a virtual pair to swap. If the center swaps, it reduces both counts by one, leaving $\min(l,r)\le1$ and both counts below quota. The new output raises its buffer count to one. Even the relaxed predicate for a second center swap would now require at least two remaining pairs on **both** input links.

There is a further test because the code visits other nodes before draining the request. At an endpoint the new virtual pair is the only pair on that input to a possible backward swap. The ordinary predicate requires at least two. The relaxed predicate requires pressure at that endpoint. Generating and swapping have left the endpoint holding at most its center-side quota's worth of qubits, including its share of the virtual pair. When $a,b>0$, each quota is strictly less than $M$. The endpoint has only one physical neighbor, whose local reservation also has size $M$. Neither pressure condition can hold there. Thus no endpoint reverses the swap, regardless of node visit order. The waiting request consumes the output, and the settled-state conditions above hold again. This proves the induction, including the step from the initially empty state.

**2. Corrected balancing.** When $a,b\ge2$, the first arrival on each side eventually gives both links positive inventory. Thereafter $\min(l,r)=1$ after each service phase. If a generation would raise the minimum to two, one center swap reduces it to one. All recurrent states are therefore on the two arms

$$
\{(l,1):1\le l\le a\}\ \cup\ \{(1,r):1\le r\le b\}.
$$

There is exactly one such state for each integer $d\in[1-b,a-1]$. A left generation increases $d$ by one unless $d=a-1$, where the left quota is full. A right generation decreases $d$ by one unless $d=1-b$. Swapping preserves $d$. These moves connect the whole interval because both rates are positive. If either quota is below two, both links can never simultaneously hold the two inputs per side required for a first balancing swap.

**3. Pressure relaxation.** If both quotas are positive, a settled state with $l=a$ has $r=0$, since otherwise the center would have swapped under pressure. Similarly $r=b$ implies $l=0$. Thus a left generation is blocked exactly at $d=a$, a right generation exactly at $d=-b$. Everywhere else the corresponding arrival is admitted, and any center swap preserves $d$. The projected walk reflects on $[-b,a]$ from the first event.

For completeness, if either quota is one, the reachable settled inventories lie on the two axes. Every axis state within quota is reachable and $d$ identifies it uniquely. For $a,b\ge2$ the full recurrent inventory class consists of

* the four one-sided states $(a,0),(a-1,0),(0,b),(0,b-1)$, and
* the positive states with $l<a$, $r<b$ and $\min(l,r)=1$.

The four one-sided states occupy the two outside positions at each end of the interval. Each other value of $d$ occurs in exactly one of the positive states. On a positive state an admitted generation either keeps the minimum at one below both quotas, raises the minimum to two and triggers a swap, or fills a quota when the other side holds just one pair and triggers a swap to an outside state. From $(a,0)$ a right arrival swaps to $(a-1,0)$. From $(a-1,0)$ a left arrival fills that quota and a right arrival leads to $(a-1,1)$. The reflected statements hold at the other end. These transitions keep the listed class closed and connect its states. Starting from any reachable inventory, the finite irreducible projected walk almost surely hits $d=a$, forcing $(a,0)$ and hence entrance to this class. For $M<2$, at least one link has zero quota and end-to-end service is impossible.

**4. Throughput.** Stationary neighbor flows satisfy $\pi_d\lambda_L=\pi_{d+1}\lambda_R$. Normalization gives the displayed probabilities. Every admitted left generation either remains in the left buffer or contributes to a completed swap. Thus its cumulative count minus $C(t)$ equals $l(t)$ after settling, and $l(t)\le a$. The right count obeys the same identity. By the finite-chain ergodic theorem and the Poisson arrival law, the long-run admitted rates are $\lambda_L(1-\pi_U)$ and $\lambda_R(1-\pi_L)$. Bounded inventory makes both equal to $\mu$. For equal rates the distribution is uniform, so $\mu=\lambda(1-1/n)$.

## Consequences and limits

For equal link rates and a target fraction $0<\eta<1$ of unlimited saturated service, the smallest uniform pressure budget is $\max\{2,\lceil\eta/(1-\eta)\rceil\}$. Corrected balancing requires exactly two more. For example, pressure requires nine slots per node for 90% and balancing requires eleven. This sizing statement concerns completed endpoint requests under permanent backlog. A target on generation blocking in an offered workload is a different observable. [Generation-blocking experiments](Memory_Sizing_Results.md)

With unlimited memory, pressure never activates and the policies coincide. After both links have generated at least once, $C(t)=\min\{N_L(t),N_R(t)\}-1$, where $N_L,N_R$ count generation events. Its rate is $\min(\lambda_L,\lambda_R)$, also the limit of the finite-memory rates. The unrestricted difference walk has no stationary probability distribution. If either link rate is zero, service from an empty start is zero at every budget.

At unit link rates the theorem gives $3/4$ for pressure at $M=3$, $2/3$ for balancing at $M=4$, and $4/5$ for pressure at $M=4$, matching the earlier 24-transition calculation. Quantizing Poisson times to simulator ticks can change the order of nearly simultaneous events. The formulas use continuous Poisson arrival order. [Recorded benchmark](Robustness_Results.md#saturated-service-check)

An independent executable check enumerated **1,030** one-generation transitions reachable from empty inventory for both policies at $M=1,\ldots,16$, including transient states. It computed stationary rewards directly from the joint inventory transition matrices and checked **96** rates across $(\lambda_L,\lambda_R)=(1,1),(1,2),(2,1)$. The reproduction commands are at the end of this note. [Verification script](scripts/saturated_chain_check.py)

## Offered demand at two slots

**Theorem.** Keep the continuous-time three-node model above, take $M=2$, use pressure relaxation, and replace permanent backlog by an initially empty FIFO of independent Poisson endpoint requests at rate $\delta>0$. Start with empty inventory. Let $T$ be the first time two center qubits are held in pairs with the **same** endpoint. Define

$$
\mu_2=\left(\frac{1}{\lambda_L}+\frac{1}{\lambda_R}-\frac{1}{\lambda_L+\lambda_R}\right)^{-1}.
$$

If $0<\delta\le\mu_2$, then $\Pr(T<\infty)=1$. If $\delta>\mu_2$, then $0<\Pr(T<\infty)<1$. Once the trap forms, the inventory stays fixed and all subsequent requests wait forever. The change at $\mu_2$ concerns the probability of trapping. Above it, one way to escape trapping is to keep the request queue busy forever.

**Inventory and lineage.** Call the empty inventory $E$, a single correctly originated elementary pair $L$ or $R$, and a single end-to-end pair $V$. A pair's origin at the center is the physical link whose reservation its center qubit still occupies. Let $W_L$ denote a center–left pair using the **right** reservation, and $W_R$ its reflection. Starting from $E$, the following cases exhaust the settled inventories up to trapping.

| Inventory | What the next event does |
| --- | --- |
| $E$ | A left or right generation gives $L$ or $R$. A request joins the queue. |
| $L$ or $R$ | Another generation on the occupied link is rejected. The opposite generation enables a center swap under pressure. If a request is waiting it consumes the output, leaving $E$. Otherwise $V$ remains. A request arriving before that generation joins the queue. |
| $V$ | The queue is empty. A request consumes $V$, leaving $E$. A right generation fills the right endpoint's two slots, enabling it to swap the new right pair with $V$. This creates $W_L$ because the surviving center qubit still occupies the right reservation. A left generation gives $W_R$. |
| $W_L$ or $W_R$ | In $W_L$, a right generation is rejected by the occupied right reservation. A left generation puts a second center–left pair in memory, reaching the trap. Requests simply queue. The reflected transitions hold for $W_R$. |

In the trap, the center is full and has one entangled partner. Generation cannot acquire two endpoint slots and no node has two distinct partners for a swap. There is no expiry to release a slot. Every $W$ state reaches the corresponding trap almost surely because the generation rate on the available side is positive. The four-generation word left, right, right, left constructs one such trap without any intervening request. [Swap and origin implementation](src/poqi/simulation/inventory.py) · [Deterministic regression](tests/test_pressure_policy.py) · [Observed trace](Memory_Aware_Results.md#structural-stall-and-change)

**Return of a busy queue.** While requests are waiting in inventories $E,L,R$, a center swap delivers one request and leaves $E$. From $E$, its service time $S$ is the maximum of independent exponential waiting times for the next left and right generations. Repeated attempts on the first available link leave that pair in place. Future Poisson increments are independent at each completion, so consecutive service times in the same busy period are independent with this law. Integrating $\Pr(S>t)=e^{-\lambda_Lt}+e^{-\lambda_Rt}-e^{-(\lambda_L+\lambda_R)t}$ gives $\mathbb E[S]=1/\mu_2$, which agrees with the saturated rate for $M=2$.

Count requests arriving during one customer's service as its offspring. Conditional on $S$, their number is Poisson with mean $\delta S$. The resulting Galton–Watson tree is finite exactly when the corresponding busy period ends. Its offspring count has mean $\delta/\mu_2$, positive probability of zero, and positive probability of at least two. Thus it dies out almost surely at and below mean one and has positive probability of survival above one. A busy period entered with an existing $L$ or $R$ has a possibly shorter first service, with the waiting time for the opposite generation. That first service ends almost surely and leaves finitely many descendants with the ordinary service law. This preserves almost-sure return in the subcritical and critical cases. [Branching-process extinction theorem, §6.1](https://people.math.wisc.edu/~roch/mdp/roch-mdp-chap6.pdf)

**Repeated opportunities to trap.** At empty inventory and empty queue, the probability that the next four events are left, right, right, left generations is

$$
\varepsilon=\frac{\lambda_L^2\lambda_R^2}{(\lambda_L+\lambda_R+\delta)^4}>0.
$$

That word reaches the trap before any return to the starting state. When $\delta\le\mu_2$, each excursion otherwise either reaches a $W$ state or returns to empty inventory and queue almost surely. Indeed, the next request arrives in finite time. If a virtual pair is waiting, that request empties the system. If it finds $E,L$ or $R$, the busy period just analyzed ends with empty inventory and queue. By independence of future Poisson events at each return, the probability of surviving $k$ excursions without trapping is at most $(1-\varepsilon)^k$. This proves almost-sure trapping, including at critical load. When $\delta>\mu_2$, the same four-event word gives positive trapping probability. There is also positive probability that the first event is a request and that its busy period never ends. On this event every virtual output is consumed immediately, so neither a wrong-origin pair nor the trap can form.

**Long-run service and queue growth.** Let $Q(t)$ count pending requests. On almost every trajectory the limiting rates are

| Eventual outcome | $\lim_{t\to\infty}C(t)/t$ | $\lim_{t\to\infty}Q(t)/t$ |
| --- | --- | --- |
| The inventory traps | $0$ | $\delta$ |
| The inventory never traps (positive probability only for $\delta>\mu_2$) | $\mu_2$ | $\delta-\mu_2$ |

After a trap there are finitely many prior completions and every new request joins the queue. At any load, infinitely many returns to empty inventory and queue while avoiding the trap have probability zero by the same four-event bound. On a nontrapping trajectory, time spent idle at the last return is almost surely finite, since the next request arrives in finite time. Any finite busy period would return the system to the empty state. Hence eventually a busy period runs forever. The renewal law of large numbers for the independent service times $S$ gives $C(t)/t\to1/\mathbb E[S]=\mu_2$ on this branch. The event of survival can depend on those times, but the renewal limit holds almost surely for the full independent sequence, hence also on survival. Subtracting completions from the independent Poisson request count gives the stated queue rate on both branches. Thus for every positive offered rate the queue grows at a positive asymptotic rate almost surely in this two-slot, no-expiry model.

At $\lambda_L=\lambda_R=1$ the threshold is $2/3$ request per unit time. Earlier ten-seed experiments observed the absorbing inventory in 10/10 runs at offered rate 0.5, 9/10 at 0.75 and 6/10 at 1.0. Those are finite-horizon counts from the rounded-tick simulator. The theorem classifies an eventual event in continuous time. The cutoff-10 runs and the slotted Q-CAST comparison have different transitions. [Offered-demand experiment](Robustness_Results.md#two-slot-failure-and-expiry) · [Two-slot transition checker](scripts/two_slot_chain_check.py)

### Which swap rules admit the trap

The trap needs one swap at an endpoint, joining a cached end-to-end pair to a fresh elementary pair. Two published protocols for continuous entanglement distribution exclude that swap by construction, for reasons unrelated to keeping the network live.

- Talsma, Iñesta and Wehner let a node swap only links held in differently-oriented qubits. A qubit's orientation is the physical neighbor it generates entanglement with. They adopt the condition to avoid "unnecessary" swaps and note that edge nodes of a chain cannot swap. Their analysis assumes enough memory to hold every link until its cutoff and names limited memory as open. [Phys. Rev. A 110, 022429 (2024), Algorithm 1, step 3.2, and Fig. 4](https://arxiv.org/abs/2402.01527)
- Iñesta and Wehner let node $i$ swap links to $j$ and $k$ only if $j$ and $k$ are not physical neighbors. Their nodes hold a fixed number of qubits per physical neighbor, as here, and every link has a finite cutoff. [Phys. Rev. A 108, 052615 (2023), Algorithm 1, step 3.2](https://arxiv.org/abs/2307.01406)

On this chain either condition forbids the endpoint swap. Neither paper considers what happens without its condition, and both rely on cutoffs.

The max-min balancing rule of Mutolo, Parekh and Rubenstein is different in kind. It compares pair counts and places no condition on where the two qubits came from. Its authors list a swap by a pivot far from two nearby nodes as an inefficiency to reduce later. Pressure relaxation inherits that freedom and lowers the threshold far enough for the endpoint swap to fire at two slots. Ordinary balancing avoids the trap at this budget only because it performs no swap at all there.

The theorem is therefore a statement about count-based swap rules under hard per-neighbor reservations and no expiry. On this chain a direction condition separates eventual permanent lockup from a stable queue, and omitting it costs most at light load. [Balancing rule, §4, and discussion, §6](papers/hotnets25-final271.pdf) · [Queue stability with the condition](Guarded_Chain_Theorem.md)

### Probability of eventually locking from empty

The same argument gives an exact risk for an initially empty system. Write $u=\lambda_L$, $v=\lambda_R$, $c=u+v$, and $k=c+\delta$. For a fresh service time $S=\max(\mathrm{Exp}(u),\mathrm{Exp}(v))$ with independent inputs, its Laplace transform follows by integrating its density,

$$
\phi(t)=\mathbb E[e^{-tS}]=\frac{u}{u+t}+\frac{v}{v+t}-\frac{c}{c+t}.
$$

Let $z$ be the probability that a busy period from one job and empty inventory returns to zero jobs. The offspring generating function in the proof gives $z$ as the **smallest** root of $z=\phi(\delta(1-z))$ in $[0,1]$. Put $s=\delta(1-z)$. Below and at the threshold $z=1$. Above the threshold, $s$ is the unique positive solution of $\delta[1/(u+s)+1/(v+s)-1/(c+s)]=1$.

Start one excursion at empty inventory and zero waiting requests. The probability $h$ of trapping before the next return is the chance of making a virtual pair before the first request, multiplied by the chance that another generation reaches that cached pair before a request consumes it. Hence

$$
h=\phi(\delta)\frac{c}{k}.
$$

The other way to avoid returning is to enter a busy period that lasts forever. Its probability in one excursion is

$$
e=\frac{\delta}{k}(1-z)
  +\frac{u}{k}\frac{\delta}{v+\delta}\frac{s}{v+s}
  +\frac{v}{k}\frac{\delta}{u+\delta}\frac{s}{u+s}.
$$

The three terms correspond to the first event being a request, a left generation, or a right generation. In the second case, after the first left generation the request must beat the missing right generation. Once that request arrives, the time to its first completion is exponential of rate $v$. If $A$ more requests arrive during that time, all their busy periods clear with probability $z^A$. Averaging gives $v/(v+s)$ for clearing, hence $s/(v+s)$ for escaping. The third case exchanges the two links. A request that finds a cached virtual pair returns the system to empty immediately. These cases exhaust the excursion. Independent regeneration yields $P=h+(1-h-e)P$, so **$P=h/(h+e)$**.

| Unit generation rate on each link | Eventual lock probability from empty | Observed locks by the end of the earlier runs |
| --- | ---: | ---: |
| $\delta=0.5$ | 1 | 10/10 |
| $\delta=2/3$ | 1 | outside the original grid |
| $\delta=0.75$ | 0.815271 | 9/10 |
| $\delta=1$ | $6\sqrt{2}-8 \approx 0.485281$ | 6/10 |

The finite-window counts give context for the derivation. No parameter was fitted to those counts. As a separate check, the [probability calculation](scripts/two_slot_lock_probability.py) solves first-event equations on the simulator-checked inventory phases, stopping at a wrong-origin pair or at queue length $K$. The probability of reaching a wrong-origin pair first is a lower bound. After reaching $K$, the first completion leaves at least $K-1$ jobs at empty inventory, so the remaining probability of ever locking is at most $z^{K-1}$. The program checks these inequalities numerically at $K=8,32,128$ across 15 rate settings. For unit links and $\delta=0.75$, the $K=128$ interval rounds outward to $[0.8152706461,0.8152706469]$. At critical load the same calculation gives only $[0.98966,1]$ after outward rounding. The probability-one conclusion there follows from the extinction proof. [Numerical results](results/memory/saturated-chain-theorem-02/offered-probabilities.json)

The [offered-demand transition check](scripts/two_slot_chain_check.py) exercised **87** outgoing transitions from 29 reachable inventory and backlog representatives at queue lengths zero through three. It checked both mirror traps through the public simulator, preserving the physical origin at each endpoint. In the proof, all queue lengths above one have the same inventory transitions and differ only in the outstanding request count. [Simulator witnesses](results/memory/saturated-chain-theorem-02/offered-transitions.json) · [Saturated joint-inventory checks](results/memory/saturated-chain-theorem-02/check.json)

Run the three checks from the repository root using the environment in the README.

~~~powershell
.\.venv\Scripts\python.exe -B scripts/saturated_chain_check.py
.\.venv\Scripts\python.exe -B scripts/two_slot_chain_check.py
.\.venv\Scripts\python.exe -B scripts/two_slot_lock_probability.py
~~~

Prior work on the saturated rates is listed under [What is recovered and what is new](#what-is-recovered-and-what-is-new).

# An orientation rule restores queue stability on the two-slot chain

With two memory slots per node and no expiry, the original pressure-relaxed policy eventually stops serving requests almost surely at or below its saturated service rate. Requiring the two qubits consumed **at the swapping node** to have different physical-link origins removes the responsible endpoint swap. The guarded policy can then sustain every strictly subcritical request rate and retains the saturated throughput of the original policy. The physical-neighbor orientation rule comes from Talsma, Iñesta and Wehner. The result here characterizes what that rule changes for pressure relaxation with an explicit request queue. [Unguarded chain theorem](Saturated_Chain_Theorem.md#offered-demand-at-two-slots) · [Talsma, Iñesta and Wehner, Algorithm 1, step 3.2](https://doi.org/10.1103/PhysRevA.110.022429)

## Model and result

Consider a left–center–right chain, initially empty. Each node has two hard memory slots. The center reserves one per physical neighbor, and each endpoint has two for its sole neighbor. Left and right generation attempts form independent Poisson processes of positive rates $u$ and $v$. Each offers one successful elementary pair, subject to admission. An independent Poisson process of rate $\delta>0$ offers unit endpoint-to-endpoint requests to an unbounded FIFO. Swaps succeed, consume one pair on each input, and preserve the physical origins of the surviving qubits. Storage has no expiry. Each event is processed separately in continuous time. After the event the policy swaps to quiescence, drains the queue, and waits for the next external event. [Inventory and origin accounting](src/poqi/simulation/inventory.py) · [Settling and FIFO service](src/poqi/simulation/sequence_adapter.py)

The `pressure_oriented` policy requires distinct origins at the pivot for **both** the ordinary balancing predicate and its pressure relaxation. Other eligibility rules and service timing are as in `pressure_relaxed`. Let $Q(t)$ and $C(t)$ count pending and completed requests. Define the mean service time $m$ and saturated service rate $\mu_2$ by

$$
m=\frac1u+\frac1v-\frac1{u+v},\qquad \mu_2=\frac1m.
$$

**Theorem.** On its reachable inventory and queue states, the guarded continuous-time chain has the following classification. The limits hold almost surely.

| Offered rate | Recurrence of the empty-inventory, empty-queue state | $\lim C(t)/t$ | $\lim Q(t)/t$ |
| --- | --- | --- | --- |
| $0<\delta<\mu_2$ | Positive recurrent, with finite mean return time | $\delta$ | $0$ |
| $\delta=\mu_2$ | Null recurrent, with almost-sure return and infinite mean return time | $\mu_2$ | $0$ |
| $\delta>\mu_2$ | Transient, with a final busy period that lasts forever | $\mu_2$ | $\delta-\mu_2$ |

For equal link rates $u=v=\lambda$, the threshold is $2\lambda/3$. At the threshold the long-run arrival and completion rates agree even though the process has no stationary probability distribution.

## Which inventories can occur?

Write $L,R$ for elementary pairs and $V$ for an endpoint-to-endpoint pair. Juxtaposition denotes simultaneous storage, and $E$ is empty. Every qubit at a degree-one endpoint originated on the same physical link, so the guard excludes all endpoint swaps. A center qubit can therefore only belong to an elementary pair from its own reservation. The center admits at most one $L$ and one $R$. When both are present and the output buffer is empty, the relaxed predicate enables a center swap, since the center is full. When one $V$ is present, that predicate would require two pairs per input to produce a second $V$.

The table gives every post-event state with $Q=0$. A subscript 1 denotes one waiting request. Entries without a subscript have an empty queue.

| Before event | Left generation | Right generation | Request |
| --- | --- | --- | --- |
| $E$ | $L$ | $R$ | $E_1$ |
| $L$ | $L$ | $V$ | $L_1$ |
| $R$ | $V$ | $R$ | $R_1$ |
| $V$ | $VL$ | $VR$ | $E$ |
| $VL$ | $VL$ | $VLR$ | $L$ |
| $VR$ | $VLR$ | $VR$ | $R$ |
| $VLR$ | $VLR$ | $VLR$ | $LR$ |
| $LR$ | $V$ | $V$ | $E$ |

In $VLR$, a request consumes the cached $V$ after settling. This leaves $LR$ with the center full. At the next generation event admission fails, but settling still turns the existing $LR$ into $V$. If the next event is a request instead, settling creates $V$ and that request consumes it at the same timestamp. Advancing directly from $VLR$ to $V$ upon consumption would change this boundary behavior.

For $Q=q\ge1$, only $E,L,R$ occur. A new request increments $q$. From $E$, generation on either side supplies its half. From $L$ or $R$, another same-side attempt leaves the state unchanged. An opposite-side attempt completes one request and leaves $E$ with $q-1$ pending. These rules and the table are closed under every event. Each listed state is accessible from the initial state by a finite event sequence. Conversely, from a finite positive queue, a string of alternating generations with no new requests empties the system with positive probability. From any idle cache, consecutive requests either empty it or enter the positive queue. Hence the reachable count states form one communicating class. Monotone counters, timestamps and pair IDs play no role in its recurrence.

## Proof of the queue classification

**Time until a busy period.** Define a busy period to start when the post-event queue first becomes positive and to end on its next visit to zero. Without another generation, at most two requests can be served from any idle stock, one using a cached $V$ and one using the two elementary pairs. Consequently, three consecutive request events force a positive queue from any idle state. In each disjoint block of three events this specific event pattern has probability $(\delta/(u+v+\delta))^3>0$. The time to reach a positive queue from any idle cache has finite mean. The same bound applies when observation stops earlier at a return to $(E,0)$.

**Time until a busy period clears.** A service that starts with empty inventory takes $S=\max(X_L,X_R)$, with independent $X_L\sim\mathrm{Exp}(u)$ and $X_R\sim\mathrm{Exp}(v)$. Its mean is $m$, obtained by integrating $\Pr(S>t)=e^{-ut}+e^{-vt}-e^{-(u+v)t}$. Every completion during a busy period restores empty inventory. While requests remain, successive services therefore have independent copies of $S$. If the first request finds $L$ or $R$, its initial service only waits for the missing link. Either initial service has finite mean at most $m$.

Requests arriving during one ordinary service give that service a mixed Poisson offspring count, with conditional mean $\delta S$ and unconditional mean $\delta m$. The busy period clears exactly when the associated Galton–Watson family is finite. Below mean one, its expected total service duration from an ordinary first service is $m/(1-\delta m)$, by summing expected service over generations. A shorter initial service of mean $x$ likewise has finite expected total duration $x/(1-\delta m)$. At mean one the nondegenerate family dies out almost surely but has infinite expected total service duration. Above mean one it survives with positive probability. An exceptional first service has finitely many arrivals almost surely, so it preserves almost-sure extinction at or below the threshold. [Branching-process extinction, Theorems 6.1.5–6.1.6](https://people.math.wisc.edu/~roch/mdp/roch-mdp-chap6.pdf) · [Welch on exceptional first services](https://doi.org/10.1287/opre.12.5.736)

A clearing busy period ends specifically at $(E,0)$. Below threshold, the bounds on the idle and busy portions give finite expected return time after leaving $(E,0)$. At threshold every excursion returns almost surely, but with probability $\delta/(u+v+\delta)$ its first event is a request finding $E$, which initiates an ordinary critical busy period of infinite mean. This proves null recurrence. Above threshold this same first event has positive probability of initiating an infinite busy period. Independence at successive clean returns rules out infinitely many returns without such an escape. The idle portion of every excursion ends almost surely, and every finite busy period would make another return. Thus an infinite busy period eventually starts almost surely.

**Rates, including the critical case.** Below threshold, successive clean return cycles have finite mean length. At time $t$ the elapsed time since the last return is $o(t)$ almost surely, by the renewal law. The queue at $t$ is bounded by the number of arrivals since that return. The Poisson law of large numbers gives $Q(t)/t\to0$, and request conservation gives $C(t)/t\to\delta$. Above threshold, after the final busy period begins, the renewal law for ordinary services gives $C(t)/t\to1/m$. Conservation then gives $Q(t)/t\to\delta-1/m$.

At critical load, null recurrence implies the fraction of time in the eight idle states tends to zero. To see why this still gives sublinear backlog, define a workload $W=0$ when $q=0$. For $q\ge1$ and inventory $h\in\{E,L,R\}$ put

$$
W(q,h)=(q-1)m+x_h,\qquad x_E=m,\quad x_L=1/v,\quad x_R=1/u.
$$

On positive-queue states, the instantaneous drift of $W$ is $\delta m-1$. An arrival adds $m$. At $L$ or $R$ the missing-side generation reduces the remaining expected service time to zero. At $E$, first-event conditioning gives $u(x_L-m)+v(x_R-m)=-1$. At critical load the drift is therefore zero on the busy states and bounded on the finite idle set. Its time integral divided by $t$ vanishes. The compensated workload is a martingale with bounded jumps and bounded jump rate. Its quadratic variation grows at most linearly in expectation, so its value divided by $t$ tends to zero almost surely by the martingale strong law. Thus $W(t)/t\to0$. Since $W-mQ$ is bounded, $Q(t)/t\to0$ and $C(t)/t\to\delta$ follow.

## Saturated control

With a request always waiting, the guarded and unguarded pressure policies follow the **same inventory and service trajectory** from empty on this chain. At two slots, only $E,L,R$ occur after consumption. The center swaps distinct-origin qubits as soon as the second side arrives. The new output is consumed before another generation can fill an endpoint and enable reversal.

The pathwise equality extends to the finite uniform budgets in the earlier saturated theorem. With positive center quotas, each endpoint holds at most its own link's center quota immediately after a center swap, strictly below its local memory limit. With a single newly created virtual pair, the endpoint satisfies neither the ordinary swap predicate nor the pressure condition. All center inputs meanwhile retain opposite origins. Thus the guard removes no executed swap under permanent backlog. If one quota is zero neither policy can make an endpoint pair from empty. The offered-demand queue classification proved above applies specifically at two slots. [Saturated theorem and endpoint argument](Saturated_Chain_Theorem.md#proof)

## Executable verification

The two-slot checker replayed all three next events from **17 reachable representatives** covering the eight idle inventories and the three busy inventories at backlog levels one, two and three. All **51 transitions** matched the predicted inventory, retained qubit origins, pending queue and completion counts. Every executed swap was at the center. Direct stationary reward calculations recovered $2/3$ for $(u,v)=(1,1)$ and $6/7$ for both $(1,2)$ and $(2,1)$. The transition table above covers arbitrary positive backlog because each busy transition depends only on its inventory and whether a completion empties the queue. [Saved two-slot results](results/memory/guarded-chain-01/check.json)

The checker also compared guarded and unguarded transitions under permanent backlog at every uniform budget from 1 through 16. All **486** one-generation transitions and completion counts agreed. From the project root, repeat both checks with the following command. [Verification script](scripts/guarded_chain_check.py)

```powershell
.\.venv\Scripts\python.exe -B scripts/guarded_chain_check.py
```

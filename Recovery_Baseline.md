# A recovery baseline for the low-memory corner

Without recovery, path-oblivious swapping on cycles of 8 and 12 nodes at two and three slots serves between 0% and 37% of a light offered load in the measurement windows. Most demand pairs receive nothing. On smaller five- and six-node cycles, concrete event sequences freeze the inventory permanently under both production pressure policies. [Uncapped freeze certificates](evidence/theory/uncapped-freezes.json)

A generation blocked by a stored pair may evict that pair unless it is an elementary pair on the same link. With zero patience and reserved slots, the finite graph with capped queues contains no starving closed class in 22 network and budget cases under all five swap rules, or on the five-cycle at four slots under the two rules enumerated. This rules out a reachable frozen inventory for those cases. In the two-slot experiments with reservations and the orientation rule, the eight- and twelve-node cycles reach 0.97 and 1.00 of the nominal offered load. Every demand pair receives service during the measurement window in all six seeds of each cell. The mean costs are 6.20 and 7.89 dropped pairs per completion, respectively.

Three further results follow.

- **Patience trades waste for outage.** Waiting before the drop cuts the waste and lengthens the outages. At two slots on the 8-cycle, service falls from 97% at zero patience to 42% at patience 30. From four slots on the simulated cycles, patience of 5 or more gives service within 0.02 of the runs without recovery.
- **The two tested cutoffs deliver less service on the two-slot cycles.** On the 8-cycle a cutoff of 10 serves 70% and a cutoff of 30 serves 56%, against 97% for the zero-patience drop.
- **Shared memory also permits freezes.** With one shared pool of slots per node, each of the 21 enumerated cases has a starving closed class in the capped graph under all five swap rules. On the three-node chain one neighbor can fill the whole center pool with elementary pairs and permanently block the other link. In the simulated networks the shared pool without recovery serves at most 9% at each tested budget under the orientation rule.

Every network-scale result now carries interruption, outage and per-demand starvation measurements. [Definitions](#metrics-in-every-run)

## The drop-when-stuck rule

A generation on link $(u,v)$ is blocked at $u$ when $u$ has no free slot for it. Under per-neighbor reservations that means $u$'s reservation toward $v$ is full. The rule acts only then.

1. At each blocked end, the candidates are the pairs that hold the contested slots. Under reservations these are the qubits that were generated toward the same neighbor. With a shared pool they are all qubits at the node.
2. An elementary pair of the link $(u,v)$ itself is never a candidate. Replacing it by a new one would change nothing.
3. A candidate must have been stored for at least the patience $W$, counted from its generation or from the swap that produced it.
4. The longest-stored candidate at each blocked end is dropped and the new pair is admitted. If one blocked end has no candidate, nothing is dropped.

The two link endpoints choose victims using their occupancy and the stored pairs' origins and ages. They act when generation is blocked. The model assumes instantaneous coordination and charges one remote invalidation notification per dropped pair. It does not measure a distributed handshake. With $W=\infty$ the rule is off. [Implementation](src/poqi/simulation/inventory.py) · [Simulator option](src/poqi/simulation/sequence_adapter.py)

It differs from a cutoff in two ways. A pair that blocks nothing is never dropped, however old. A pair that blocks a link is dropped after $W$, however long the memory could have kept it.

## Metrics in every run

The root simulator now reports a `service_continuity` block in every result, on a measurement window after a warm-up.

- **Interruption.** An interval in which a request of a demand pair waits and no request of that pair completes. Arrivals do not restart it. A completion ends it and starts the next one if a request still waits. Lengths are clipped to the window. The interval still open at the horizon counts with its observed length and is flagged as right-censored. This is the definition used for the diamond. [Guarded diamond](Guarded_Diamond_Results.md#who-receives-service)
- **Outage.** An interruption at least as long as a stated threshold. The runs below use 50 time units, which is 50 mean generation times of one link.
- **Starved pair.** A demand pair with a request waiting in the window and no completion in it.
- **Satisfaction.** Completions in the window divided by the window length times the nominal request rate. It can exceed one, because realized arrivals vary and a backlog from the warm-up can be served in the window.

The block gives these per demand pair and for all pairs together, with the least satisfaction over pairs and Jain's index. The memory sweep writes the starved-pair count and the longest interruption of each run to its tables. Requests can also be served from one queue per demand pair, so that a pair that cannot be served does not hold back the others. The exhaustive search has always used that service rule. All runs here use it. [Tests](tests/test_recovery_baseline.py)

## Exhaustive verdicts

The search of the lockup note was rerun with the drop rule at zero patience and with shared-pool admission. Each cell counts the swap rules for which the finite graph contains a reachable closed class with no completion of at least one demand pair. Queue lengths at or above the cap share one state label. The graph contains the projection of every concrete trajectory; successive abstract transitions may use different hidden backlogs. Absence of a starving closed class rules out a concrete frozen inventory for those inputs. Partial starvation and queue stability require separate arguments for unbounded queues. [Projection argument and freeze criterion](Lockup_Extensions.md#how-the-cases-were-decided)

| Network and demand pairs | Slots | Reservations | Reservations and drop | Shared pool | Shared pool and drop |
| --- | ---: | --- | --- | --- | --- |
| Chain, 3 nodes, 0–2 | 2 | 1 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 3 nodes, 0–2 | 3 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 3 nodes, 0–2 | 4 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 4 nodes, 0–3 | 2 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 4 nodes, 0–3 | 3 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 4 nodes, 0–3 | 4 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 5 nodes, 0–4 | 2 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 5 nodes, 0–4 | 3 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 5 nodes, 0–4 and 1–3 | 2 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Chain, 5 nodes, 0–4 and 1–3 | 3 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Diamond, 0–3, 0–1, 1–2 | 2 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Diamond, 0–3, 0–1, 1–2 | 3 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Diamond, 0–3, 1–2 | 2 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Diamond, 0–3, 1–2 | 3 | 2 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Star, 3 leaves, all leaf pairs | 3 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| Star, 3 leaves, all leaf pairs | 4 | 0 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| 5-cycle, 0–2 | 2 | 5 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| 5-cycle, 0–2 | 3 | 5 of 5 | 0 of 5 | 5 of 5 | 0 of the 1 run |
| 5-cycle, 0–2 | 4 | 2 of 5 | 0 of the 2 run | – | – |
| 5-cycle, 0–2 and 1–3 | 2 | 5 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| 6-cycle, 0–3 | 2 | 5 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |
| 6-cycle, 0–3 | 3 | 5 of 5 | 0 of 5 | – | – |
| 6-cycle, 0–3 and 1–4 | 2 | 5 of 5 | 0 of 5 | 5 of 5 | 0 of 5 |

No expiry, uniform budgets, pressure relaxation with each swap condition. With the drop rule a state records the storage order of all pairs, because the victim is the longest-stored candidate. The search and the public simulator agree on random event words for both variants.

- **Zero-patience drop.** All 213 completed graph searches lack a starving closed class, 112 under reservations and 101 with a shared pool.
- **Shared pool without recovery.** All 105 finite graphs contain a starving closed class. On the three-node chain, filling every center slot from one neighbor gives a concrete permanent freeze at three and four slots, even with the orientation rule. The reservation graphs at those budgets contain no starving closed class.

Three large cases were stopped before they finished, because the state that records storage order grows quickly: the 5-cycle at four slots, the 6-cycle at three slots with a shared pool, and the 5-cycle at three slots with a shared pool and the drop rule. Their cells show what completed. The verdicts are for zero patience. A positive patience makes the rule depend on time, which the untimed search cannot represent.

## Network-scale runs

Cycles of 8 and 12 nodes and open grids of 3×3 and 4×4 nodes, with unit generation rate on every link. Each seed draws its demand pairs from the node pairs at distance two or more. Their number is 12% of all node pairs, which gives 3, 8, 4 and 14 pairs. All pairs of one network have the same request rate. It is set so that shortest-path service would use 10% of all generated pairs. The same seed gives every arm the same demand pairs, generation times and request times. Six seeds, horizon 2000, measurement window $[500, 2000)$, no expiry unless the arm is a cutoff. 2,880 runs in total.

The load is light on purpose. With eight slots and the orientation rule every network serves it in full, so a shortfall at fewer slots is a memory effect.

### Service under reservations

Satisfaction of the whole offered load, mean of six seeds, orientation rule. Drop arms are labeled by patience and cutoff arms by lifetime.

| Network | Slots | No recovery | Drop 0 | Drop 5 | Drop 30 | Cutoff 10 | Cutoff 30 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8-cycle | 2 | 0.11 | 0.97 | 0.61 | 0.42 | 0.70 | 0.56 |
| 8-cycle | 3 | 0.37 | 0.97 | 0.94 | 0.88 | 0.95 | 0.90 |
| 8-cycle | 4 | 0.96 | 0.98 | 0.97 | 0.96 | 0.97 | 0.97 |
| 8-cycle | 8 | 0.97 | 0.97 | 0.97 | 0.97 | 0.97 | 0.97 |
| 12-cycle | 2 | 0.17 | 1.00 | 0.91 | 0.67 | 0.94 | 0.84 |
| 12-cycle | 3 | 0.15 | 1.04 | 1.03 | 1.01 | 1.04 | 1.02 |
| 12-cycle | 4 | 1.03 | 1.00 | 1.03 | 1.03 | 1.02 | 1.03 |
| 12-cycle | 8 | 1.03 | 1.01 | 1.02 | 1.03 | 1.01 | 1.02 |
| 3×3 grid | 2 | 0.00 | 0.29 | 0.14 | 0.03 | 0.16 | 0.07 |
| 3×3 grid | 3 | 0.43 | 1.01 | 1.01 | 1.02 | 1.02 | 1.02 |
| 3×3 grid | 4 | 0.77 | 1.00 | 0.97 | 0.97 | 0.98 | 0.98 |
| 3×3 grid | 8 | 1.02 | 1.02 | 1.02 | 1.02 | 1.02 | 1.02 |
| 4×4 grid | 2 | 0.08 | 0.14 | 0.10 | 0.08 | 0.12 | 0.08 |
| 4×4 grid | 3 | 0.24 | 0.86 | 0.90 | 0.82 | 0.90 | 0.86 |
| 4×4 grid | 4 | 0.97 | 0.96 | 0.97 | 0.97 | 0.97 | 0.97 |
| 4×4 grid | 8 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Paired over seeds, the zero-patience drop raises satisfaction on the 8-cycle at two slots by 0.86 [0.57, 1.15] and on the 12-cycle by 0.83 [0.60, 1.06]. Every seed on both cycles gained service. Individual gains range from 0.29 to 0.99 on the 8-cycle and from 0.45 to 1.04 on the 12-cycle. At three slots the mean gains are 0.60 [0.25, 0.94] and 0.90 [0.73, 1.06], and on the 4×4 grid 0.62 [0.46, 0.77]. Brackets are pointwise 95% Student-t intervals.

**Starvation without recovery.** Runs with at least one starved demand pair, of six seeds: 8-cycle 6 and 6 at two and three slots, 12-cycle 6 and 5, 4×4 grid 6 and 6, 3×3 grid 6, 3 and 2 at two, three and four slots. Averaged over seeds, 61% to 89% of the demand pairs were starved on the cycles at these budgets. Above these budgets no pair was starved.

**Starvation with recovery.** On the cycles, and on the grids from three slots, no demand pair was starved in any run of any drop or cutoff arm. That is 1,080 runs with a drop rule under reservations.

**Two slots on a grid is a different failure.** A node divides its slots among its links. With two slots and three or four links, some links get no slot and can never generate. Without recovery nothing is served on the 3×3 grid, and every recovery arm still leaves 71% to 89% of the demand pairs starved on both grids. This is the cost of reservations when a node has fewer slots than links. The shared pool does not have it. [Shared pool results](#shared-pool-admission-at-network-scale)

**The original pressure policy.** At two slots on a cycle it is pathwise identical to the orientation rule, because each node has one slot per neighbor. At three slots without recovery it completed nothing in any run on either cycle. With the zero-patience drop it served 0.97 and 1.01. On the 3×3 grid at three and four slots, the original policy served every pair, while the orientation rule left a pair unserved in three and two of the six runs, respectively. The five-cycle search also gives an example where adding a swap restriction introduces a starving closed class in the capped graph. At six and eight slots the long-distance pairs on the 12-cycle still receive little service under the original policy, with minimum satisfaction as low as 0.09. [Chain and cycle comparisons](Lockup_Extensions.md#longer-chains)

### What patience costs and buys

Two slots, orientation rule, reserved memory. Outage share is the fraction of the window that a demand pair spends in interruptions of 50 or more, averaged over pairs. The longest interruption is the worst pair's, averaged over seeds. Each seed's cost divides drops during $[500,2000)$ by completions in that same window. The table reports the mean of the six seed-level ratios.

| Network | Arm | Satisfaction | Outage share | Longest interruption | Dropped pairs per served request |
| --- | --- | ---: | ---: | ---: | ---: |
| 8-cycle | No recovery | 0.11 | 0.89 | 1500 | – |
| 8-cycle | Drop 0 | 0.97 | 0.01 | 49 | 6.20 |
| 8-cycle | Drop 2 | 0.87 | 0.10 | 88 | 1.55 |
| 8-cycle | Drop 5 | 0.61 | 0.44 | 166 | 1.22 |
| 8-cycle | Drop 10 | 0.47 | 0.68 | 352 | 0.95 |
| 8-cycle | Drop 30 | 0.42 | 0.78 | 582 | 0.44 |
| 8-cycle | Cutoff 10 | 0.70 | 0.26 | 134 | – |
| 8-cycle | Cutoff 30 | 0.56 | 0.59 | 250 | – |
| 12-cycle | No recovery | 0.17 | 0.87 | 1500 | – |
| 12-cycle | Drop 0 | 1.00 | 0.14 | 143 | 7.89 |
| 12-cycle | Drop 2 | 0.98 | 0.23 | 193 | 1.29 |
| 12-cycle | Drop 5 | 0.91 | 0.50 | 267 | 0.71 |
| 12-cycle | Drop 10 | 0.78 | 0.61 | 458 | 0.44 |
| 12-cycle | Drop 30 | 0.67 | 0.73 | 709 | 0.19 |
| 12-cycle | Cutoff 10 | 0.94 | 0.33 | 194 | – |
| 12-cycle | Cutoff 30 | 0.84 | 0.58 | 389 | – |

The outage share is not zero on the 12-cycle even with ample memory. At eight slots without recovery it is 0.10, because the longest demand pairs wait more than 50 between services at this load. The zero-patience value of 0.14 at two slots is close to that floor.

- **Zero patience improves service on both two-slot cycles.** Against a cutoff of 10 at two slots it serves 0.27 [0.12, 0.43] more on the 8-cycle and 0.06 [0.03, 0.10] more on the 12-cycle. On the 4×4 grid at three slots the cutoff serves 0.04 [0.01, 0.07] more.
- **Zero patience keeps dropping when memory is ample.** At eight slots under the orientation rule it drops 4.53 pairs per completion on the 8-cycle and 5.66 on the 12-cycle. Each drop replaces a stored pair with a generation that would otherwise have been rejected. On the 12-cycle the satisfaction loss relative to no recovery was 0.04 [0.01, 0.07] at four slots and 0.02 [0.00, 0.04] at eight.
- **Patience reduces the cost at larger budgets.** From four slots on the cycles and on the 4×4 grid, and from six on the 3×3 grid, patience of 5 or more gives at most 0.54 dropped pairs per completion. Mean satisfaction differs from no recovery by at most 0.02 in those cells.

### Shared-pool admission at network scale

The same runs with one shared pool of slots per node. Satisfaction, mean of six seeds, orientation rule.

| Network | Slots | No recovery | Drop 0 | Drop 5 | Cutoff 30 | Drop 0 under reservations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8-cycle | 2 | 0.00 | 0.97 | 0.34 | 0.04 | 0.97 |
| 8-cycle | 4 | 0.00 | 0.97 | 0.89 | 0.43 | 0.98 |
| 8-cycle | 8 | 0.05 | 0.97 | 0.97 | 0.96 | 0.97 |
| 12-cycle | 2 | 0.00 | 1.03 | 0.42 | 0.04 | 1.00 |
| 12-cycle | 4 | 0.06 | 1.01 | 0.91 | 0.44 | 1.00 |
| 12-cycle | 8 | 0.02 | 1.03 | 1.01 | 0.98 | 1.01 |
| 3×3 grid | 2 | 0.00 | 1.03 | 0.37 | 0.05 | 0.29 |
| 3×3 grid | 4 | 0.04 | 1.02 | 0.99 | 0.71 | 1.00 |
| 3×3 grid | 8 | 0.04 | 1.02 | 1.02 | 1.02 | 1.02 |
| 4×4 grid | 2 | 0.00 | 0.99 | 0.40 | 0.04 | 0.14 |
| 4×4 grid | 4 | 0.00 | 0.87 | 0.87 | 0.67 | 0.96 |
| 4×4 grid | 8 | 0.05 | 0.83 | 0.83 | 0.87 | 1.00 |

- **Without recovery the shared pool fails at every budget.** Under the orientation rule, 104 of 120 runs completed nothing in the window, and every run had a starved pair. More memory does not help within this range, because one neighbor can fill any pool. The original pressure policy does the same up to four slots and reaches 0.19 to 0.70 at eight.
- **With the zero-patience drop it serves from two slots on all four networks.** That includes both grids, where reservations leave links without a slot. No pair was starved in any shared-pool run with a drop rule under the orientation rule.
- **The swap policy still matters under recovery.** With immediate drops in a shared pool, the original pressure policy left at least one demand pair without a completion in 29 of 120 runs. These included all six seeds at both four and six slots on the 4×4 grid. Adding the orientation rule gave service to every demand pair in all 120 matched runs. The counts measure starvation over 1,500 time units.
- **It is not uniformly better.** On the 4×4 grid from four slots the shared pool with the drop rule serves less than reservations, by 0.10 [0.04, 0.16] at four slots and 0.17 [0.09, 0.25] at eight. Its least-served pair gets 0.23 at eight slots against 0.77.
- **A cutoff alone does not rescue a shared pool at small budgets.** A cutoff of 30 serves 4% at two slots and under half at four slots on the cycles.

## What this changes for the crossover map

At this load, immediate recovery gave each demand pair at least one completion on the simulated cycles from two reserved slots and on grids from three reserved slots. With shared slots and the orientation rule, every pair received service from two slots on both topology families. These finite-window outcomes motivate comparisons of throughput, delay and resource cost against planned routing.

This note does not make that comparison. It has no planned-path arm. It fixes the arms the sweep should carry at small budgets. A reasonable choice is the zero-patience drop as the path-oblivious baseline and patience 5 as a sensitivity arm, both reported next to the run without recovery.

## Limits

- One offered load, 0.1 in the normalization above, and one demand share. Heavier loads were not run.
- Each cell has six seeds and a window of 1,500. Reusing each seed across policies enables paired comparisons. Counts pooled across budgets and arms describe repeated workloads. The reported intervals are pointwise.
- The search covers zero patience only. With reserved slots and positive patience, every demand pair received service on the cycles and on grids with at least three slots in these runs.
- The finite-graph verdicts apply to the listed inputs. The absence of a starving closed class excludes a concrete frozen inventory in each corresponding unbounded-queue model. Whether one class can starve while other classes keep receiving service, and whether queues are stable, remain open in general. The larger networks were simulated for a finite window.
- Drops and endpoint coordination are instantaneous in these runs. Each drop contributes one modeled invalidation notification.
- Satisfaction is relative to the nominal rate. Mean latency covers requests completed during the measurement window, including their wait before the window if applicable. It omits requests still waiting at the horizon.
- The threshold for an outage is 50. The seed records include per-pair interruption counts, total time, maximum length, right-censoring and outage share at that threshold. To estimate outage shares at a different threshold, rerun with `--outage`.

## Reproduce

From the repository root, initialize the pinned SeQUeNCe submodule and use the Python environment described in the README. The simulation commands start from empty inventory and generate all 2,880 trajectories from seeds. They work in a fresh checkout without an earlier result directory. Use new output paths on each run.

```powershell
.\.venv\Scripts\python.exe -B scripts/recovery_baseline.py --output results/memory/recovery-baseline-rerun/reserved --gzip --workers 19
.\.venv\Scripts\python.exe -B scripts/recovery_baseline.py --output results/memory/recovery-baseline-rerun/tail-drop --admissions tail_drop --arms none drop0 drop5 cutoff30 --gzip --workers 19
.\.venv\Scripts\python.exe -B scripts/audit_recovery_results.py results/memory/recovery-baseline-rerun
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py cycle5 --memory 2 3 --all-rules --drop-stuck
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py chain --memory 2 3 4 --all-rules --admission tail_drop
.\.venv\Scripts\python.exe -B scripts/dead_state_search.py diamond --memory 2 --admission tail_drop --drop-stuck --check
.\.venv\Scripts\python.exe -B -m pytest tests/test_recovery_baseline.py -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/recovery-baseline-tests
```

Earlier runs combined whole-run drops, swaps and expiries with post-warm-up completions. The 2,880 regenerated rows use the same half-open measurement window for every operation and completion count. Ratios with zero completions are undefined. The audit checked all 480 group summaries and compared ten service and continuity fields per trajectory with the original local records. All 28,800 comparisons matched exactly. The tagged evidence can be audited without those earlier local files. [Audit result](evidence/recovery/audit.json) · [Audit code](scripts/audit_recovery_results.py)

The manifests give the seed lists, demand pairs, software versions, source hashes and checksums for the compressed JSON files. [Reservation manifest](evidence/recovery/reserved/manifest.json) · [Shared-pool manifest](evidence/recovery/tail-drop/manifest.json) · [Runner](scripts/recovery_baseline.py) · [Search](scripts/dead_state_search.py) · [Historical search verdicts](evidence/recovery/lockup-scan.jsonl)

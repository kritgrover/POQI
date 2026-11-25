# Does a local swap guard prevent diamond stalls?

At two qubits per node, the local origin guard leaves every swap unchanged on this diamond. Both policies reached a permanently frozen inventory in 10 of 10 archived runs and 8 of 10 fresh runs with lossy links and no expiry. At four qubits, the guard improved total service on lossy links and reduced mean backlog. Individual demand classes experienced different changes in their longest interruption.

## What changes at two versus four qubits

The guard allows pressure relaxation to swap only if the two consumed qubits at the pivot were originally generated toward **different physical neighbors**. A qubit can retain its generation origin through a swap even when its current entangled partner changes. The guard applies to every swap, including those that already satisfy ordinary balancing. Selection can skip an older incompatible concrete input pair within a candidate pair of partners. The original swap preference, pressure threshold and reservation rules still apply. [Policy implementation](src/poqi/simulation/sequence_adapter.py) · [Quotas and origins](src/poqi/simulation/inventory.py)

Each diamond node has two physical neighbors. A two-qubit node reserves one qubit for each neighbor. Generation respects these quotas, and swapping preserves the generation origin of every surviving endpoint. Two occupied qubits at a common pivot therefore already have different origins. **The two policies are pathwise identical at this budget** under either lifetime on matched inputs. All 40 simulated two-qubit policy pairs had identical full histories, including allocations, swaps, consumption, expiry, and final inventory. A two-slot chain leaf has two slots reserved for its one neighbor and can behave differently. [Unguarded chain theorem](Saturated_Chain_Theorem.md) · [Guarded chain theorem](Guarded_Chain_Theorem.md) · [Archived diamond stall certificates](QCAST_Concurrent_Results.md)

At four qubits, each neighbor has a quota of two. Same-origin swaps now occur. They disappeared under the guard on every run, and every four-qubit policy pair had different histories.

## Matched experiment

The experiment uses the existing concurrent-service diamond, with edges 01, 02, 13, and 23. Each edge has two link trials per slot. Requests for 03, 01, and 12 have independent Poisson rates .50, .25, and .15. Memory starts empty. Each swap consumes one pair on each input and succeeds with certainty. Both policies keep inventory across slots, either indefinitely or with inherited cutoff 10. A cutoff is measured in slots from generation. Swap products inherit the earliest input deadline. The primary condition has two qubits per node and link success probability .5. Four-qubit controls use link success .5 and 1. [Workload, opportunities and queue conventions](QCAST_Concurrent_Protocol.md)

All 240 trajectories run for 400 slots. The measured completion window is (100,400], with physical costs in slots starting 100–399. Within a seed, each pair uses the same requests, channel ordering and potential successes. The runner compared the 60 unchanged baseline trajectories from seeds 7271–7280 with their full historical records and reproduced all 60 exactly. Fresh seeds 8271–8280 give a second cohort of ten paired observations per condition. The tables report pointwise 95% Student-t intervals across paired seeds, retaining all zero-service runs. The cohorts are reported separately. These finite windows do not establish service stability, the population probability of trapping, or performance on other networks.

## Throughput and backlog

Rates are completed requests per time unit. Changes are guarded minus original pressure. Backlog is the time average of requests waiting, measured from actual arrival.

| Qubits | Link success | Cutoff | Original rate, fresh | Guarded rate, fresh | Fresh rate change [95% CI] | Archived rate change [95% CI] | Fresh mean backlog, original → guarded |
| ---: | ---: | --- | ---: | ---: | --- | --- | --- |
| 2 | .5 | None | .0587 | .0587 | 0 [0, 0] | 0 [0, 0] | 206.46 → 206.46 |
| 2 | .5 | 10 | .3207 | .3207 | 0 [0, 0] | 0 [0, 0] | 147.22 → 147.22 |
| 4 | .5 | None | .6070 | .7290 | +.1220 [.1053, .1387] | +.1260 [.1093, .1427] | 74.31 → 42.98 |
| 4 | .5 | 10 | .6050 | .7267 | +.1217 [.1025, .1409] | +.1297 [.1059, .1535] | 75.40 → 43.07 |
| 4 | 1 | None | .8950 | .9013 | +.0063 [−.0006, .0133] | .0000 [−.0172, .0172] | 4.83 → 2.36 |
| 4 | 1 | 10 | .8950 | .8967 | +.0017 [−.0090, .0123] | −.0023 [−.0230, .0183] | 5.13 → 3.76 |

At four qubits with lossy links and no expiry, mean backlog fell by 31.33 requests [25.26, 37.41] on fresh seeds. Over 300 measured slots, mean attempts fell from 1,664.0 to 1,520.7 and mean swaps fell from 647.9 to 541.2. With cutoff 10, mean expired pairs rose from 1.4 to 7.5 per run. The guarded rate stayed below the total offered load of .90 under both lifetimes.

![Paired effect of the local origin guard on diamond service and interruptions](results/qcast/guarded-diamond-02/guard_tradeoff.png)

## Who receives service

Fresh seeds, four qubits, link success .5. Each interruption is a continuous interval with at least one request of the stated class waiting and no completion of that class. Repeated arrivals do not restart the interval. A completion splits it even if other requests remain. The longest interval is clipped to the measurement window and averaged over seeds.

| Cutoff | Class | Original rate | Guarded rate | Rate change [95% CI] | Mean backlog, original → guarded | Longest interruption, original → guarded |
| --- | --- | ---: | ---: | --- | --- | --- |
| None | 03 | .2083 | .3243 | +.1160 [.0991, .1329] | 69.05 → 40.99 | 17.80 → 16.10 |
| None | 01 | .2560 | .2537 | −.0023 [−.0100, .0054] | .85 → 1.28 | 7.77 → 9.96 |
| None | 12 | .1427 | .1510 | +.0083 [−.0018, .0185] | 4.41 → .71 | 22.43 → 10.71 |
| 10 | 03 | .2053 | .3200 | +.1147 [.0957, .1336] | 70.03 → 41.14 | 19.00 → 15.30 |
| 10 | 01 | .2560 | .2547 | −.0013 [−.0057, .0030] | .84 → 1.15 | 7.65 → 9.60 |
| 10 | 12 | .1437 | .1520 | +.0083 [.0002, .0165] | 4.53 → .77 | 22.10 → 10.84 |

Most of the throughput gain went to 03. For 12 without expiry, the longest observed interruption shortened by 11.73 slots [6.42, 17.03], even though its throughput difference remained unresolved. Across all classes combined, the longest interruption grew from 6.5 to 8.7 slots, a paired increase of 2.20 [.45, 3.95]. An aggregate interruption ends on *any* service, so its duration can move differently from the interruption for a specific class.

The perfect-link controls reveal a further tradeoff. With cutoff 10, the longest observed interruption for 01 grew from 3.46 to 16.92 slots, an increase of 13.46 [8.17, 18.75]. For 12 it fell from 19.92 to 9.32, a decrease of 10.60 [4.60, 16.61]. Total throughput changed by just .0017 [−.0090, .0123]. The per-class numerical results for both cohorts include backlog, zero service, longest interruption, observed gaps of at least 10 slots, and the unfinished trailing interval. [All paired estimates](results/qcast/guarded-diamond-02/summary.json)

## Permanent loss of service and temporary interruptions

The physical certificate checks that every allowed demand pair is absent, every generation edge is blocked by memory or an origin quota, and every possible swap is disabled. With unbounded lifetimes this state is permanent for the fixed demand mix. With finite lifetimes the same conditions guarantee inactivity only until an expiry. The observer counts measured slots that start in this disabled state while at least one visible request is pending after start-of-slot service.

With two qubits and no expiry, the eight certified fresh seeds entered their traps by slot 20. In the other two fresh runs, seeds 8278 and 8279, the system continued serving 01. Neither 03 nor 12 received any measured completion across all ten fresh runs. The terminal aggregate service interruption reached the full 300-slot measurement window for each of the eight certified runs. With cutoff 10 the fresh mean longest aggregate interruption was 20.3 slots and per-class rates were .0420 for 03, .1863 for 01 and .0923 for 12.

On fresh seeds, the two-qubit system spent an average of **240 of 300 measured slots** physically disabled with demand waiting without expiry. With cutoff 10, that average fell to **82.5 slots**, or 27.5% of the window, under either policy. On archived seeds the corresponding figures were 300 and 85.1. No four-qubit run met this sufficient physical criterion. The measured four-qubit interruptions therefore need their own service-based interpretation.

An unfinished observed interruption is right-censored at slot 400. Its observed length enters the summaries even if no completion occurs. The right-censoring flag means a request remains waiting at 400. If a completion at 400 leaves other demand waiting, the new trailing interval has observed length zero. Only the physical certificate justifies labeling a state permanently frozen.

## Verification and reproduction

The checker reconstructs slot reservations, physical generations, concrete swap inputs, inherited deadlines and generation origins, and surviving inventory. Separate checks cover seed-matched opportunities, concurrent per-pair service at both boundaries, conservation, and chronological queue-area integration. Each compressed full trajectory has a SHA-256 digest. The manifest records source hashes. To regenerate in a new directory or verify the saved experiment in place, run from the repository root.

```powershell
.\.venv\Scripts\python.exe -B scripts/qcast_guarded_diamond.py results/qcast/guarded-diamond-reproduction --workers 3
.\.venv\Scripts\python.exe -B scripts/qcast_guarded_diamond.py results/qcast/guarded-diamond-02 --workers 3 --verify
.\.venv\Scripts\python.exe -B scripts/guarded_diamond_plot.py results/qcast/guarded-diamond-02
.\.venv\Scripts\python.exe -B -m pytest tests/test_qcast_guarded_diamond.py -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/guarded-diamond-tests
```

[Runner and checks](scripts/qcast_guarded_diamond.py) · [Focused tests](tests/test_qcast_guarded_diamond.py) · [Manifest](results/qcast/guarded-diamond-02/manifest.json) · [Seed-level measurements and raw file hashes](results/qcast/guarded-diamond-02/observations.json)

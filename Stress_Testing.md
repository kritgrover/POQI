# Stress testing the guarded three-node chain

The symmetric no-expiry checks recovered the theorem’s exact saturated rates. The stress tests also found two reversals. With two slots at each endpoint, increasing the center from four slots to six **reduced** its exact service rate from 4/5 to 2/3. With a cutoff of one time unit, a 4–6–4 chain served **0.3297** requests per unit time under permanent backlog, compared with **0.5523** on a 2–2–2 chain under the same arrivals.

## What was held fixed

One repeater connects two endpoints. Both physical links offer one successful elementary pair per unit time on average, using independent Poisson clocks. Swaps are immediate and perfect, consume one pair on each input, and use the guarded pressure policy. The center reserves its slots as evenly as possible between the links. The endpoints share a single FIFO demand class. “Endpoint slots” is the budget at **each** endpoint. A finite cutoff is a lifetime in time units from generation. A swapped pair inherits the earliest input deadline.

We ran 14 distinct hardware/lifetime configurations on six matched seeds, 9161–9166. Each ran from empty inventory to time 2,000. Measurements cover [400, 2,000). In the saturated run a request was always waiting. In the offered run independent requests arrived at nominal rate 0.5, with a measured mean of 0.4950 across these seeds. Two additional offered-demand controls at the baseline bring the total to **180 simulations**. Rates are completions per time unit. Mean queue is the time average of pending requests, and queue growth is the change between the window boundaries divided by 1,600. Intervals are pointwise 95% Student-t intervals across the six seeds. The comparison intervals in the text use within-seed differences.

The [guarded stability theorem](Guarded_Chain_Theorem.md) classifies the offered queue at two slots per node without expiry. Under permanent backlog, the [uniform-budget theorem](Saturated_Chain_Theorem.md) also gives the exact no-expiry rate for the other uniform budgets. The nonuniform no-expiry benchmarks below come from separate exact state calculations. The offered-demand results outside the two-slot no-expiry case are finite-window observations.

## 1. Change only the uniform memory budget

All three nodes receive the same budget. Storage has no expiry.

| Endpoint slots | Center slots | Cutoff | Exact saturated rate | Measured saturated rate [95% interval] | Service at load 0.5 | Mean queue at load 0.5 | Queue growth/time at load 0.5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2 | ∞ | 2/3 | 0.6598 [0.6537, 0.6659] | 0.4949 | 1.22 | 0.0001 |
| 3 | 3 | ∞ | 3/4 | 0.7423 [0.7318, 0.7528] | 0.4946 | 0.58 | 0.0004 |
| 4 | 4 | ∞ | 4/5 | 0.7926 [0.7814, 0.8039] | 0.4948 | 0.21 | 0.0002 |
| 6 | 6 | ∞ | 6/7 | 0.8489 [0.8363, 0.8614] | 0.4950 | 0.04 | 0.0000 |

An exact check of the reachable saturated inventories recovered $M/(M+1)$ at all four budgets. The largest discrepancy between the simulated and exact rates was 0.0083 per unit time. The two-slot mean of 0.6598 fell just below 2/3, and its six-seed interval narrowly missed that limit. At load 0.5, larger budgets mainly shortened the queue because the guarded baseline was already keeping up with arrivals.

**Direct offered-load controls at two slots.** At load 0.5, the guarded queue served 0.4949 per unit time and its measured growth was 0.0001 [−0.0018, 0.0020]. Under identical inputs, unguarded pressure completed zero requests during the measured window on all six seeds. Each final inventory met the permanent-lock certificate: a full center with only one partner, pending end-to-end requests, and no expiry. At load 0.8 the guard served 0.6598 and its queue grew by 0.1447 [0.1211, 0.1683] per unit time. The theorem predicts limiting growth of $0.8-2/3=0.1333\ldots$. The exact recurrence classification at critical load was outside this small simulation grid.

## 2. Change only the repeater’s slots

The endpoints stay at two slots each. Storage has no expiry.

| Endpoint slots | Center slots | Cutoff | Exact saturated rate | Measured saturated rate [95% interval] | Service at load 0.5 | Mean queue at load 0.5 | Queue growth/time at load 0.5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2 | ∞ | 2/3 | 0.6598 [0.6537, 0.6659] | 0.4949 | 1.22 | 0.0001 |
| 2 | 3 | ∞ | 3/4 | 0.7423 [0.7318, 0.7528] | 0.4946 | 0.71 | 0.0004 |
| 2 | 4 | ∞ | 4/5 | 0.7926 [0.7814, 0.8039] | 0.4948 | 0.58 | 0.0002 |
| 2 | 6 | ∞ | 2/3 | 0.6598 [0.6537, 0.6659] | 0.4949 | 1.65 | 0.0001 |

The six-slot center reserves three slots per neighbor. Each endpoint can supply at most two pairs, so neither center reservation can fill and the center cannot reach its total pressure threshold. Under permanent backlog the center falls back on ordinary balancing, retaining one elementary pair on each side. Its only recurrent left/right inventories are (1,1), (1,2), and (2,1). This yields exactly 2/3. The measured four-to-six-slot change was **−0.1328 [−0.1408, −0.1248]**. This is a counterexample to the extrapolation that adding repeater memory always increases service under this policy.

## 3. Change only expiry

All three nodes stay at two slots. The cutoff of 0.5 is half the mean time between offers on one link.

| Endpoint slots | Center slots | Cutoff | Exact saturated rate | Measured saturated rate [95% interval] | Service at load 0.5 | Mean queue at load 0.5 | Queue growth/time at load 0.5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 2 | ∞ | 2/3 | 0.6598 [0.6537, 0.6659] | 0.4949 | 1.22 | 0.0001 |
| 2 | 2 | 0.5 | 0.4404 | 0.4361 [0.4201, 0.4522] | 0.4361 | 79.27 | 0.0589 |
| 2 | 2 | 1 | 0.5584 | 0.5523 [0.5448, 0.5598] | 0.4951 | 6.31 | -0.0001 |
| 2 | 2 | 3 | 0.6552 | 0.6493 [0.6405, 0.6580] | 0.4949 | 1.74 | 0.0001 |
| 2 | 2 | 10 | 0.6667 | 0.6598 [0.6537, 0.6659] | 0.4948 | 1.23 | 0.0002 |

The cutoff of 0.5 reduced saturated service below the offered rate of 0.5. The measured queue grew by **0.0589 [0.0270, 0.0907]** per unit time. With cutoff 1 the service kept pace during the window, although the mean queue was 6.31, compared with 1.22 without expiry.

There is a short independent benchmark for these **two-slot saturated** cutoff rows. Starting empty, the first link offer takes mean time 1/2. Its pair then waits for the other unit-rate link for at most $T$ time units. A match occurs with probability $p=1-e^{-T}$ and the mean time in this waiting phase is also $p$. Either a match followed by immediate consumption or an expiry returns the inventory to empty. Hence the exact rate for this experiment is $p/(1/2+p)$. At cutoff 10 that rate is 0.6666566, very close to the no-expiry limit. The measured saturated throughput happened to be identical to baseline on this sample.

This two-slot cutoff rate is a known result. It equals the unit-memory throughput of Mai et al. at equal rates, equal holding limits and no swap or reset delay. It is also the reciprocal of the mean service time derived by Lo Piparo, Munro and Nemoto. [Mai et al., Theorem 1, Eq. (7)](https://arxiv.org/abs/2608.11429) · [Lo Piparo, Munro and Nemoto, appendix](https://arxiv.org/abs/2603.24874)

## 4. Change memory, repeater slots, and expiry together

Start with the uniform budget of four, then give the center two additional slots. The first row is the matched no-expiry control for this 4–6–4 layout. Section 3 supplies the corresponding two-slot controls.

| Endpoint slots | Center slots | Cutoff | Exact saturated rate | Measured saturated rate [95% interval] | Service at load 0.5 | Mean queue at load 0.5 | Queue growth/time at load 0.5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 6 | ∞ | 6/7 | 0.8489 [0.8363, 0.8614] | 0.4949 | 0.15 | 0.0001 |
| 4 | 6 | 1 | — | 0.3297 [0.3174, 0.3420] | 0.3297 | 211.14 | 0.1653 |
| 4 | 6 | 10 | — | 0.8486 [0.8360, 0.8613] | 0.4949 | 0.19 | 0.0001 |

Increasing the layout from 2–2–2 to 4–6–4 **raised** saturated service by 0.1891 [0.1781, 0.2000] without expiry and by 0.1889 [0.1779, 0.1998] at cutoff 10. At cutoff 1 the same layout change **lowered** it by 0.2226 [0.2147, 0.2305]. The 4–6–4 queue then grew by 0.1653 [0.1371, 0.1935] per unit time at load 0.5.

A deterministic replay isolates one way this happens. With a request waiting at time zero, the left pair arrived at 0.1 and the right pair at 0.2. At cutoff 1, the 2–2–2 center filled and immediately completed the request at 0.2. The 4–6–4 center held one pair per link, below both its ordinary swapping threshold and its pressure threshold. With no further arrivals, the pairs expired at 1.1 and 1.2 and the request remained outstanding. This trace explains how additional slots can delay an otherwise useful swap beyond its deadline.

## Verification and reproduction

The no-expiry calculation enumerated both next-link events from every reachable saturated inventory, extracted the unique closed class, and summed its completion rewards. For uniform budgets 2, 3, 4, and 6 the recurrent classes had 3, 4, 5, and 7 states. With endpoints fixed at two and center budgets 3, 4, and 6 they had 4, 5, and 3 states. The 4–6–4 case had 7. In each case the incoming transition counts give a uniform stationary distribution at unit link rates. [Existing transition enumerator](scripts/saturated_chain_check.py)

<details>
<summary>Reproduce the simulations from this file</summary>

From the project root, run the following PowerShell command. It reads the embedded Python and prints the six observations and summary for each condition. Optional case IDs after the command select individual settings, for example `r4 r6`. Use `--checks` to rerun the exact no-expiry benchmarks and the two-arrival cutoff trace. Times in the random simulations use 100 million simulator ticks per unit.

~~~powershell
.\.venv\Scripts\python.exe -B -c "from pathlib import Path; body = Path('Stress_Testing.md').read_text(encoding='utf-8'); code = body.split('~~~' + 'python' + chr(10), 1)[1].split(chr(10) + '~~~', 1)[0]; exec(compile(code, 'stress_testing', 'exec'))"
~~~

~~~python
import json
import random
import statistics
import sys
import networkx as nx
from scipy.stats import t
from poqi.simulation import run_simulation

SEEDS = range(9161, 9167)
H, W, TICKS = 2000, 400, 100_000_000
LEFT, RIGHT, END = (0, 1), (1, 2), (0, 2)
CASES = {
    "base": (2, 2, None), "u3": (3, 3, None), "u4": (4, 4, None),
    "u6": (6, 6, None), "r3": (2, 3, None), "r4": (2, 4, None),
    "r6": (2, 6, None), "t05": (2, 2, 0.5), "t1": (2, 2, 1), "t3": (2, 2, 3),
    "t10": (2, 2, 10), "mix0": (4, 6, None), "mix1": (4, 6, 1),
    "mix10": (4, 6, 10),
}
graph = nx.path_graph(3)
nx.set_edge_attributes(graph, 1.0, "generation_capacity")

def stream(seed, index, kind, edge, rate):
    rng = random.Random((seed + 1) * 1000003 + index)
    time = rng.expovariate(rate)
    events = []
    while time < H:
        tick = round(time * TICKS)
        if tick < H * TICKS:
            events.append(dict(kind=kind, endpoints=edge, time=tick / TICKS))
        time += rng.expovariate(rate)
    return events

def run(case, seed, mode, policy):
    end_slots, center_slots, cutoff = CASES[case]
    left = stream(seed, 0, "generate", LEFT, 1)
    right = stream(seed, 1, "generate", RIGHT, 1)
    if mode == "sat":
        arrivals = [dict(kind="request", endpoints=END, time=0,
                         count=1 + min(len(left), len(right)))]
    else:
        arrivals = stream(seed, 2, "request", END, float(mode))
    events = left + right + arrivals
    out = run_simulation(graph, {END: 1 if mode == "sat" else float(mode)},
                         memory_slots={0:end_slots, 1:center_slots, 2:end_slots},
                         cutoff_time=cutoff, swap_policy=policy, horizon=H,
                         trace=events, ticks_per_time_unit=TICKS)
    q = q0 = done = expired = offered = 0
    area = 0.0
    last = W
    for event in out["events"]:
        kind, time = event["kind"], event["time"]
        if kind == "expire" and W <= time < H:
            expired += 1
        if kind not in ("request", "complete"):
            continue
        if time >= W:
            area += q * (time-last)
            last = time
            done += int(kind == "complete")
            offered += int(kind == "request")
        q += 1 if kind == "request" else -1
        if time < W:
            q0 = q
    area += q * (H-last)
    assert q == out["unserved_requests"] and q-q0 == offered-done
    assert out["pair_conservation_residual"] == 0
    if mode == "sat":
        assert q > 0  # all requests arrived at zero, so backlog never emptied
    live = out["live_pairs"]
    trap = (cutoff is None and q > 0 and len(live) == center_slots
            and {tuple(p["endpoints"]) for p in live} in ({LEFT}, {RIGHT}))
    return dict(service=done/(H-W), mean_q=area/(H-W), drift=(q-q0)/(H-W),
                expiry=expired/(H-W), offered=offered/(H-W), trap=int(trap))

def interval(values):
    avg = statistics.mean(values)
    half = t.ppf(.975, len(values)-1)*statistics.stdev(values)/len(values)**.5
    return [avg, avg-half, avg+half]

if sys.argv[1:] == ["--checks"]:
    from collections import Counter
    from fractions import Fraction
    from scripts.saturated_chain_check import reachable_transitions
    targets = {"base":"2/3", "u3":"3/4", "u4":"4/5", "u6":"6/7",
               "r3":"3/4", "r4":"4/5", "r6":"2/3", "mix0":"6/7"}
    for case, target_rate in targets.items():
        e, c, _ = CASES[case]
        moves = reachable_transitions({0:e, 1:c, 2:e}, "pressure_oriented")
        walk = nx.DiGraph()
        for state, options in moves.items():
            walk.add_edges_from((state, dest) for dest, _ in options)
        closed, = nx.attracting_components(walk)
        incoming = Counter(dest for s in closed for dest, _ in moves[s])
        assert set(incoming) == closed and set(incoming.values()) == {2}
        rate = Fraction(sum(done for s in closed for _, done in moves[s]), len(closed))
        assert rate == Fraction(target_rate)
        print(case, "recurrent inventories", len(closed), "exact rate", rate)
    trace = [dict(kind="request", endpoints=END, time=0),
             dict(kind="generate", endpoints=LEFT, time=0.1),
             dict(kind="generate", endpoints=RIGHT, time=0.2)]
    for e, c, expected in [(2, 2, (1, 0)), (4, 6, (0, 2))]:
        out = run_simulation(graph, {END:0.5}, memory_slots={0:e, 1:c, 2:e},
                             cutoff_time=1, swap_policy="pressure_oriented",
                             horizon=2, trace=trace)
        assert (out["completed_requests"], out["expired_pairs"]) == expected
        print((e,c,e), [(v["time"],v["kind"]) for v in out["events"]
                        if v["kind"] in ("complete","expire")])
    raise SystemExit

selected = sys.argv[1:] or list(CASES)
for case in selected:
    experiments = [("sat", "pressure_oriented"), ("0.5", "pressure_oriented")]
    if case == "base":
        experiments += [("0.8", "pressure_oriented"), ("0.5", "pressure_relaxed")]
    for mode, policy in experiments:
        rows = [run(case, seed, mode, policy) for seed in SEEDS]
        print(json.dumps(dict(case=case, mode=mode, policy=policy,
                              stats={k:interval([r[k] for r in rows]) for k in rows[0]},
                              rows=rows)), flush=True)
~~~

</details>

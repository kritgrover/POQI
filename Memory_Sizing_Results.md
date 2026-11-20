# Blocking-based memory sizing

## Experiment

Point 4: compare sizing from mean occupancy with sizing for **1% rejected pair-generation attempts**. Simulator dynamics are unchanged; the new analysis replays its event logs.

- **Chain:** three nodes, D=1, generation rate 1 on each physical link, endpoint demand rate 1, corrected balancing, reserved admission. Test the existing no-expiry setting and a separate inherited-cutoff-10 setting.
- **Control:** one direct link, generation rate 1, deterministic lifetime 10, no requests or swaps. This is an M/D/c/c loss system; both endpoints are occupied together, so there is one shared blocking event.
- **Calibration:** five unlimited-memory runs, seeds **1271-1275**. **Validation:** ten independent seeds **3271-3280**, matched across slot budgets within each scenario. Budgets are selected from calibration before validation.
- **Time:** H=4,000 abstract units, first 1,000 excluded from rate/occupancy measurements. Empty initial inventory. Additional no-expiry calibration runs use H=2,000, warm-up 500, with the same five calibration seeds; these are a paired horizon check, not extra independent repetitions.

Main experiments are separate from short software smoke runs. Reported 95% intervals are pointwise Student-t intervals across validation runs, not across individual arrivals. They do not propagate calibration uncertainty. This is a pilot with ten validation repetitions per budget.

## Models and residence measurements

Erlang offered load is `a = offered_generation_rate * mean_slot_holding_time`. **Physical endpoint holding time continues across swaps**; only pivot slots are released. The existing pair-episode residence clock restarts at every swap and cannot be substituted directly for this holding time.

Holding-time calibration uses admissions in `[1,000, 3,990)` for cutoff 10, followed through 4,000; every such lifetime is fully observed. For no expiry, admissions in `[1,000, 2,000)` are followed through 4,000, retaining censored survivors. Those estimates remain finite-window observations, not established stationary means.

The three sizing rules use the same reserved-slot allocation:

1. **Mean:** smallest uniform integer budget whose quota for every node/generation-neighbor covers its calibrated offered mean load. This tests mean-occupancy sizing; it does not change the existing prescribed-residence LP.
2. **Erlang:** calculate each quota's blocking probability using `B(0,a)=1`, `B(c,a)=a*B(c-1,a)/(c+a*B(c-1,a))`. On the chain, combine endpoint marginals as `1-(1-B_u)*(1-B_v)` and average over offered links. Select the first budget predicting at most 1% blocking. Endpoint independence and state-independent holding times are approximations for the chain.
3. **Unlimited-trajectory tail:** apply each candidate capacity and quota to the joint pre-arrival states of unlimited calibration runs. Select the first budget where at most 1% of offered attempts would fail that admission check. This retains endpoint correlation, but finite capacity changes subsequent dynamics; it is not an exact finite-system counterfactual or guarantee.

The direct control has load 10: exact Erlang-B predicts **21.458% blocking at 10 slots** and **0.714% at 18 slots**; 17 slots predicts 1.295%, so 18 is the first budget below 1%. Erlang-B permits general independent holding times, including deterministic times. See [Whitt's Erlang formulas](https://www.columbia.edu/~ww2040/ErlangBandCFormulas.pdf). Simultaneous resource requirements and state-dependent controls require additional care; see [Zachary and Ziedins, *Loss networks*](https://arxiv.org/pdf/0903.0640).

## Results

**480 trajectories completed:** 20 calibration/horizon-check runs and 460 validation runs across 46 scenario/budget conditions. Each validation row below uses ten seeds. Percentages are rejected generation attempts.

| Scenario | Sizing rule | Slots/node | Predicted blocking | Measured blocking [95% CI] |
| --- | --- | ---: | ---: | ---: |
| Direct cutoff-10 control | Mean | 10 | No loss prediction | 21.694% [21.021%, 22.367%] |
| Direct cutoff-10 control | Erlang | 18 | 0.714% | 0.598% [0.426%, 0.771%] |
| Direct cutoff-10 control | Tail | 19 | 0.558% | 0.315% [0.199%, 0.431%] |
| Chain, cutoff 10 | Mean | 8 | No loss prediction | 14.247% [13.669%, 14.824%] |
| Chain, cutoff 10 | Erlang | 19 | 0.717% | 3.653% [3.203%, 4.103%] |
| Chain, cutoff 10 | Tail | 32 | 0.799% | 0.239% [0.164%, 0.314%] |
| Chain, no expiry | Mean | 118 | No loss prediction | 0.877% [0.368%, 1.387%] |
| Chain, no expiry | Erlang | 140 | 0.834% | 0.551% [0.194%, 0.908%] |
| Chain, no expiry | Tail | 363 | 0.972% | Zero observed; sample CI [0, 0] |

**Mean sizing fails the 1% target in the control and cutoff chain.** Every control Erlang prediction falls inside its corresponding 95% interval. In the cutoff chain, Erlang improves the budget but still misses the target; tail sizing meets it conservatively. The smallest tested cutoff-chain budget meeting the target by either its mean or upper pointwise interval is **31**, not a proven minimum of 32. For no expiry, these tested crossings are **118** by the mean and **139** by the upper interval.

At the cutoff-chain budgets 8/19/32, mean throughput is **0.862/0.946/0.955** requests per time unit, versus **0.955** with unlimited memory. All recorded rejections at those three budgets are reservation-labelled; no full-slot rejection was logged. Results are conditional on reserved admission. Budgets 1-3 produce zero completed requests in every chain validation run under either lifetime setting.

The tail method is useful for conservative sizing here, but is **not the better whole-curve predictor**. Across the tested finite budgets, blocking mean absolute errors are **6.69 percentage points for Erlang versus 16.60 for tail** on the cutoff chain, and **22.07 versus 45.28** without expiry. At cutoff-chain c=19, even the endpoint-dependence envelope using the fitted Erlang marginals stays near 0.717%; endpoint correlation alone cannot explain measured blocking of 3.653%.

## Residence and horizon checks

The calibrated physical holding means below are in abstract time units. For the chain, the two means correspond to the pivot's left/right generation origins; each has offered rate 1.

| Calibration | Physical holding means | Offered load from holding means | Measured mean occupancy |
| --- | ---: | ---: | ---: |
| Direct control, one endpoint | 10.000 | 10.000 | 10.025 |
| Cutoff chain, pivot, H=4,000 | 3.809 / 3.811 | 7.620 | 7.629 |
| No-expiry chain, pivot, H=2,000 | 2.547 / 43.056 | 45.602 | 56.111 |
| No-expiry chain, pivot, H=4,000 | 5.286 / 58.269 | 63.555 | 86.738 |

All calibration cohorts happened to finish: **zero censored survivors**. The no-expiry discrepancy is not a violation of Little's law: admission-cohort holding means and time-window occupancy use different observation sets, and a stationary limit has not been established. Exact full-run occupancy-area/slot-lifetime conservation holds in every run.

Extending the no-expiry calibration from H=2,000 to H=4,000 changes mean/Erlang/tail budgets from **88/106/240** to **118/140/363**. These are horizon-sensitive pilot estimates. In contrast, the cutoff experiment has bounded lifetimes and uncensored calibration, although request-backlog stability is still a separate question.

![Measured blocking and throughput against memory budget](results/memory/blocking-point4/report/blocking.png)

Outputs: [full report](results/memory/blocking-point4/report/blocking.json), [budget recommendations](results/memory/blocking-point4/report/sizing.csv), [blocking and throughput summaries](results/memory/blocking-point4/report/summary.csv), [individual runs](results/memory/blocking-point4/report/observations.csv), [node measurements](results/memory/blocking-point4/report/nodes.csv), [origin/holding-time measurements](results/memory/blocking-point4/report/origins.csv), and [run manifest](results/memory/blocking-point4/manifest.json).

## Interpretation and validation

Blocking means rejected physical generation attempts. Full-slot and neighbor-reservation rejections are reported separately; reservation rejection can occur below total capacity. Logged reasons follow the simulator's endpoint-check order; separate local-exposure measurements retain overlapping causes. Neither blocking nor mean occupancy alone establishes request throughput. The existing deterministic tests separately demonstrate that corrected balancing at D=1 cannot swap with fewer than four pivot slots, despite physical swapping being possible with two.

Any smallest measured budget is the **smallest tested** budget. Pointwise intervals across a searched capacity grid do not certify a global minimum; zero rejections do not establish zero population loss. Finite pair lifetimes also do not establish stability of the unbounded request backlog.

The full root suite passed **307 tests**. After adding a numerical-stability regression for extremely small blocking probabilities, the final reporting suite passed **27 tests**. Coverage includes Erlang calculations, slot-lifetime/event reconstruction, tail sizing, seed separation, missing/corrupted records and report regeneration. All **480 saved records** passed replay validation and an independent audit of counts, occupancy accounting, calibration lifetimes and matched inputs. The final figure was visually checked.

New code is confined to [event-log analysis](src/poqi/analysis/blocking.py), [Erlang utilities](src/poqi/analysis/erlang.py), the [experiment/reporting script](scripts/memory_blocking_analysis.py), and their tests. No simulator, LP, admission or swapping rules changed.

## Reproduction

From the repository root, use new output directories:

```powershell
.\.venv\Scripts\python.exe -B scripts/memory_blocking_analysis.py --output results/memory/blocking-point4
.\.venv\Scripts\python.exe -B scripts/memory_blocking_analysis.py --from-runs results/memory/blocking-point4 --output results/memory/blocking-point4-reanalysis
.\.venv\Scripts\python.exe -B -m pytest tests -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/point4-tests
```

Compressed event logs and numerical reports remain under the ignored `results/` directory.

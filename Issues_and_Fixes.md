# Implementation issues and fixes

Validated: 2026-11-09. Scope: released implementation versus corrected implementation; the research contribution remains the finite-memory work.

Reference: [final HotNets paper](papers/hotnets25-final271.pdf), Sections 4-5 (PDF pages 5-6), and [arXiv v1](papers/2509.13993v1.pdf), Sections 4-5 (pages 4-5). Released Python source is pinned to `quantum-network@7c57be549c275509b1674aaab3f7341c955041db`, under `simulation-final/`; the current Rust checkout is a different version. `path_oblivious` preserves the released behavior; `path_oblivious_corrected` contains the fixes below.

## 1. Swap selection violates the current-state rule

The paper permits a swap at `x` between `y,z` only when

```text
C_yz + 1 <= min(C_xy - D, C_xz - D).
```

Among eligible outputs, choose the smallest `C_yz`.

**Cause:** the released routine builds candidates once, uses `delta=2` to admit nonminimum candidates, never increments `swap_made`, and checks only physical input availability before later swaps. Stale preference and nonminimum selection are related failures of this batch routine.

**Deterministic examples** (`D=1`, pivot `0`, neighbors in ascending order):

| Case | Initial counts | Released behavior | Corrected behavior |
| --- | --- | --- | --- |
| Stale preference | `C01=C02=C03=2`; all leaf-to-leaf counts zero | Three swaps: `(1,2)`, `(1,3)`, `(2,3)`. After the first, the second requires `1 <= min(0,1)`, which is false. | One swap `(1,2)`. Inputs become `(1,1,2)`; no further swap at this pivot is preferable. |
| Nonminimum output | `C01=C02=C03=C04=5`; `C12=0`, `C34=2`; other leaf-to-leaf counts `100` | Swaps `(1,2)` then `(3,4)`, although after the first action `(1,2)` remains eligible with count `1 < 2`. | One minimum-output swap per visit; the next visit recomputes and chooses `(1,2)` again. |

**Fix already implemented:** [corrected swap selection](SeQUeNCe/example/path_oblivious_corrected/model.py) executes one currently preferable minimum-output swap per node visit and rebuilds candidates on subsequent visits. Shuffled node passes and swapping to local quiescence remain supported. Each swap consumes `D` pairs from each input and creates one output.

**Verification added in this pass:** exact-state and minimum-choice regressions in [test_model.py](SeQUeNCe/example/path_oblivious_corrected/test_model.py); both examples also execute the actual pinned author functions from all four historical drivers in [test_parity.py](SeQUeNCe/example/path_oblivious_corrected/test_parity.py).

## 2. Overhead denominator differs from the final paper

Let `h` be physical shortest-path hop count and `S` executed swaps. Both ratios sum costs only over completed requests:

```text
Released:  S / sum(f[h-1])
           f[0]=0, f[1]=D,
           f[n]=D*(f[floor(n/2)] + f[ceil(n/2)]), n>=2.

Corrected: S / sum(s(h))
           s(1)=0,
           s(h)=D*(1 + s(floor(h/2)) + s(ceil(h/2))), h>1.
```

| Deterministic request | Released denominator | Final-paper denominator |
| --- | ---: | ---: |
| `D=2`, 3 hops | 8 | 6 |
| `D=2`, 4 hops | 20 | 10 |
| `D=1`, any `h` | `h-1` | `h-1` |

**Fix already implemented:** retain both ratios on each trajectory, index the corrected recurrence by actual hops, and return `null` for zero denominators. Tests compare with independent enumeration of binary swapping trees and now execute the denominator examples against all four pinned author drivers.

**Which figures use which metric:** the archived `simulation-final/plot_distillation_mult_pdf.py` reads `total swaps / optimal direct path sum`; `infinite-swapping.py` accumulates that sum using `f[h-1]`. Therefore that archived plotting pipeline uses **legacy overhead**. The final HotNets text defines **corrected overhead**, but the exact script/data provenance of its published figures remains **unverified**. The archived 25-node plots do not establish provenance for the final 50-node experiment. Older 50-node code also exists, without a verified connection to those figures.

The preprint prints an earlier recurrence without the additive `1` for `h>2`. Because the released code also shifts the index, its formula is not literally the preprint formula either.

## 3. Supporting accounting and comparison safeguards

These existing changes support validation; they are separate from the two rule/metric discrepancies above.

- Corrected inventory totals start from actual edge inventory rather than hard-coded `20 * edge_count`. A one-edge input containing 7 pairs must report 7, not 20. Conservation is `I_final = I_initial + generated - (2D-1)*swaps - D*completed`.
- Cost tables cover the graph's required hop lengths; the regression includes a 61-hop request beyond the released 50-entry table.
- Controlled comparisons share realized generation/request inputs and keyed node visits, and run to a fixed common horizon. Legacy cumulative-ratio stopping remains available for author parity; direct Python callers must explicitly set `stop_mode="fixed"`.
- Local quiescence is not a proof of global max-min optimality; an existing four-node counterexample tests that limitation.

## 4. Verified pilot results

Saved [cycle](SeQUeNCe/example/path_oblivious_corrected/results/cycle/manifest.json) and [grid-overlay](SeQUeNCe/example/path_oblivious_corrected/results/grid/manifest.json) comparisons: 25 nodes, 35 consumer pairs, five paired repetitions, master seed **271**, 1,000 iterations, initial inventory 20 per physical edge, Poisson batch mean 10, fixed stopping, no warm-up. Realized graph/input/substream seeds and input tapes are retained in each experiment's `inputs/input-000.json` through `input-004.json`.

| `D=1` metric | Cycle | Grid overlay |
| --- | ---: | ---: |
| Mean completions, released -> corrected | 604.0 -> 723.8 | 754.6 -> 858.2 |
| Completion increase | **19.8%** | **13.7%** |
| Paired completion difference, 95% CI | +119.8 [45.13, 194.47] | +103.6 [18.90, 188.30] |
| Mean swap overhead, released -> corrected | 2.5552 -> 2.0454 | 4.5952 -> 3.8598 |
| Overhead reduction | 20.0% | 16.0% |
| Paired overhead difference, 95% CI | -0.5098 [-0.7527, -0.2669] | -0.7354 [-1.2146, -0.2562] |

Percentages are ratios of replicate means; intervals are two-sided Student-t intervals on paired differences (`n=5`, 4 degrees of freedom), not intervals on the percentages. At `D=1` both denominator definitions coincide, so the completion gain comes from corrected dynamics. **The 14-20% statement means more completed requests under the corrected implementation, not a new method.** These are fixed-horizon pilots, not exact reproductions of the published figures or steady-state estimates. Every saved `D=2,3` run completes only 0-8 requests; no reliable ranking is claimed there.

## 5. Validation and reproduction

The fixes above predate this pass. This pass adds regression coverage and a reusable saved-result verifier; it does not change production dynamics or replace the saved experiments.

- **204 example tests passed**, including 17 new test cases and one strengthened regression: deterministic discrepancies, pinned-author parity, accounting, both metrics, shared-input replay, fixed horizons, and reporting.
- **10 verifier tests passed**, covering corrupt records, missing paired runs, undefined overhead, and generation accounting for both scheduling modes.
- **All 60 saved run records passed** independent checks of input totals, completions, nonnegative final inventory, conservation, both denominators, and overhead values.

From the repository root, with the existing environment:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'SeQUeNCe')
New-Item -ItemType Directory -Force tmp | Out-Null
.\.venv\Scripts\python.exe -B -m pytest SeQUeNCe/example/path_oblivious SeQUeNCe/example/path_oblivious_corrected -q -o addopts= -p no:cacheprovider --basetemp tmp/issues-tests
.\.venv\Scripts\python.exe -B -m pytest tests/test_implementation_results.py -q -o addopts= -p no:cacheprovider --basetemp tmp/issues-verifier-tests
.\.venv\Scripts\python.exe -B scripts/verify_implementation_results.py
```

Final-figure attribution remains open. No author contact was made; the supervisor decides whether to pursue it after the memory results are validated.

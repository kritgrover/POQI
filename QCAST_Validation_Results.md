# Q-CAST reference validation

## Scope and provenance

This milestone executes the authors' routing code on small cases; it does not
implement a persistent Q-CAST policy or establish comparative performance.
The [comparison plan](QCAST_Comparison_Plan.md) recommends separately labelled
native slotted and persistent experiments. Existing `balancing`,
`pressure_relaxed`, inventory, FIFO and experiment code remain unchanged.

Reference: [sshi27/QuantumRouting](https://github.com/sshi27/QuantumRouting/tree/0a0251dd5f38eb1669ff6abe18ab83436ddbba18),
commit **`0a0251dd5f38eb1669ff6abe18ab83436ddbba18`**, 18 November 2021.
The README identifies SIGCOMM 2020; `quantum/Plot.kt:42` maps `Online` to
Q-CAST and `Online-R` to its recovery-disabled variant. This checkout includes
post-publication fix `e2a05738892263f7bb08057d82b16817b4360b7d`, adding
utilization checks and direct-path success logging. It is not a verified
publication-time snapshot.

The authors' [paper PDF](https://users.soe.ucsc.edu/~qian/papers/QuantumRouting.pdf)
identifies *Concurrent Entanglement Routing for Quantum Networks: Model and
Designs*, Shi and Qian, SIGCOMM 2020,
[DOI 10.1145/3387514.3405853](https://doi.org/10.1145/3387514.3405853).
Downloaded PDF SHA256:
`6ad689122289f3e026b459e30469a892d9315958c654f82f67c2d1f561f37c60`.
The [2019 preprint v3](https://arxiv.org/abs/1909.09329v3), 25 October 2019,
is titled *Modeling and Designing Routing Protocols in Quantum Networks*.
The later [2024 TON paper](https://doi.org/10.1109/TNET.2023.3343748) adds
Xiaoxue Zhang as an author; its protocol changes were not audited and are not
used to interpret this 2021 code.

Initial root revision was `6a5bd5f0cc0f2d9865775c2203084d784bc8eaaa`, with
clean Git status and no applicable `AGENTS.md` found. Root dependencies and
the four requested project-record documents were inspected. No existing
Q-CAST material was found. Java/Javac **23.0.2** were available; Maven/Gradle
were absent. Docker client **28.0.4** had no available engine. Portable Maven
**3.9.9**, downloaded from Maven Central and checked against its published
SHA512, compiled the original POM with Kotlin **1.3.72** successfully. No
system installation, author GUI, plotting daemon or figure sweep was used.

## Algorithm and model audit

Source locations below refer to the pinned repository's `src/main/kotlin/quantum/`.

- **Metric and width:** `topo/Topo.kt:284` computes
  `q^(h-1) E[min_e Binomial(w,p_e)]` for `h` physical edges, homogeneous swap
  probability `q`, and edge probabilities `p_e=exp(-alpha*distance_e)`.
  `algorithm/OnlineAlgorithm.kt:82` searches widths downward, stopping at the
  first feasible width per S-D pair, and uses an extended Dijkstra search at
  that width. P2 repeatedly picks the largest resulting candidate across
  pairs on residual resources. This is not shortest-path routing or global
  optimization over all widths.
- **Resources:** each width-`w` path binds `w` channels per edge, `w` endpoint
  qubits and `2w` intermediate qubits. `Link.kt` debits capacity on assignment;
  it remains assigned until slot reset, including after failed generation or
  swapping. `Node.kt` consumes swap endpoints on success and failure.
- **Recovery:** P2Extra reserves one residual candidate for each considered
  main-path endpoint pair separated by at most `k` main-path hops. P4 repairs
  link-failure segments using preallocated routes, then swaps. `k` does not
  bound detour length. There is no retry after a failed swap. General
  overlapping-recovery behavior is not validated by the single-detour cases.
- **Information/timing:** P2 sees topology, probabilities, capacities and
  concurrent demands before the operative generation realization. P4 reads
  shared topology state. The code does not enforce a distributed `k`-hop view
  or simulate classical delays. `AlgorithmBase.work()` runs P2, generation,
  P4 and counting, then `Topo.clearEntanglements()` resets everything. No
  pair persistence, age or inherited expiry exists.
- **Accounting/randomness:** `work()` returns the number of S-D list entries
  with service and the sum of established ebits. Multiple ebits per pair are
  allowed. Duplicate S-D entries double-count the same physical ebits. P2
  also calls generation for display; the later generation stage overwrites
  those outcomes but the display draws still advance the RNG.

**Paper/code qualifications:** SIGCOMM Eq. (2) visibly prints `q^h`; the code
uses `q^(h-1)`, consistent with the number of internal swaps. For homogeneous
positive `q` this changes score magnitude by a common factor, not ranking.
Paper Algorithm 2 updates path widths during search; the code instead scans
fixed widths and stops at the widest feasible one. The paper describes XOR
recovery, including overlapping loops, and swaps at interior recovery nodes
even when not used. The code reconstructs chosen paths and has overlap
rejection checks for overlapping coverage of broken edges. The paper's
200-path cap and calibrated hop-search bound are not enforced in
`OnlineAlgorithm`. No full recovery or operation-cost parity is claimed.
The paper treats persistence as future work. Its effective link probability
can aggregate multiple link-layer trials; one code generation draw is not
evidence of one raw optical trial.

## Executed small cases

The new [Kotlin driver](scripts/qcast/ReferenceValidation.kt) calls unmodified
author classes. The [Python runner/auditor](scripts/qcast_reference.py) checks
the source revision and tracked-source cleanliness, copies only tracked build
inputs into a new results directory, adds the driver and compiles headlessly.
It hashes source/build inputs and runtime dependencies, retains logs and
failure status, and bounds build/run commands to 180/30 seconds. Its exhaustive
simple-path/binomial oracle is restricted to tiny fixtures, not a new Q-CAST
implementation.

All controlled cases use **D=1**: a swap consumes one pair on each input.
Path width is parallel capacity, not D. Unless specified otherwise,
`alpha=0` (`p=1`), planning `q=1`, `k=0`, and P4 `q=1`. Node coordinates default
to `(node_id,0)`. Link failures are deliberately injected after P2; the swap
failure case changes P4 `q` to zero after allocation. Planning probabilities
and conditional realized outcomes are recorded separately. These are
correctness fixtures, not random samples from the planning distribution.

| Case | Physical configuration / controlled outcome | Allocated effective channel attempts | Delivered ebits |
| --- | --- | ---: | ---: |
| Direct unit | Memory `[1,1]`, one channel | 1 | 1 |
| Direct memory bottleneck | Memory `[2,3]`, four channels | 2 | 2 |
| Direct channel bottleneck | Memory `[3,3]`, one channel | 1 | 1 |
| Direct partial failure | Memory `[3,3]`, three channels, first fails | 3 | 2 |
| Direct zero memory | Memory `[0,1]`, one channel | 0 | 0 |
| Chain success | `0-1-2`, memory `[1,2,1]`, one channel/edge | 2 | 1 |
| Chain blocked | Same, pivot memory one | 0 | 0 |
| Chain link failure | Same as success, edge `1-2` fails | 2 | 0 |
| Chain swap failure | Both links succeed, P4 `q=0` | 2 | 0 |
| Chain width two | Memory `[2,4,2]`, two channels/edge | 4 | 2 |
| Diamond detour | Edges `01,13,02,23`; memory `[1,1,2,1]` | 2 | 1 via `0-2-3` |
| Diamond competition | Same edges; memory two/node; demands `03,01`; planning `q=.8` | 3 | 1 per demand |
| Widest-first counterexample | Memory `[2,4,2]`; channels `01:2,12:2,02:1`; planning `q=.1` | 4 | 2 (P4 `q=1`) |
| Recovery disabled | Main `0-1-2-3`, edge `1-2` fails | 3 | 0 |
| Recovery succeeds | Same plus allocated `1-4-2` detour | 5 | 1 |
| Recovery also fails | Main `1-2` and detour `1-4` fail | 5 | 0 |

The recovery network has memory `[1,4,4,1,2]`, one channel on each of
`01,12,23,14,24`, planning `q=.9`, `k=1`, P4 `q=1`, and node 4 at `(1.5,1)`.
Successful recovery requires three swaps; failed recovery still attempts one.
Unused recovery capacity therefore has a real allocation cost. The diamond
competition allocates direct `0-1` first, then `0-2-3`; resources are exclusive.
The widest-first case picks width two with score **0.2**, although direct width
one has score **1.0**. This is an executed source-behavior distinction, not a
claim that the selected route maximizes expected yield over all widths.

Two independent metric controls gave **1.0** for direct width two at `p=.5`,
and **0.5** for a two-edge width-two chain at `p=.5,q=.8`.
Native `work()` also ran two deterministic width-two direct slots, each
returning **(served pairs=1, ebits=2)**. Eight direct `p=.5` slots with seed
**20261120**, repeated from that seed, returned ebit counts
**`1,2,1,0,1,1,1,1`**, identically on replay; all slots reset cleanly.
This short seeded check is not distributional validation. A duplicate-entry
diagnostic returned **(2,4)** for two physical ebits, confirming that backlog
multiplicity must stay outside this interface. For one unit request per S-D
pair, the direct width-two fixture provides one useful completion and one
surplus ebit; native throughput remains two ebits.

**Final validation (`validation-03`, 20 November 2026):** all **16 controlled
cases**, **17 path allocations**, **two metric controls** and the native-work
controls passed. The independent audit checks residual qubit/channel budgets,
widest-feasible candidate selection, swap endpoint/input exclusivity, physical
delivery paths and useful-versus-surplus accounting. The targeted Q-CAST plus
pressure-policy suite passed **71 tests** in 2.32 seconds. The full root suite
passed **443 tests** in 47.00 seconds, with **no skips**: the previous 400 tests
plus 43 new tests. This includes the unchanged two-slot no-expiry absorbing
failure regression and deliberate corruption of saved reference records.
Test logs: [targeted](results/qcast/targeted-tests.log) and
[full root suite](results/qcast/full-tests.log).

## Reproduction and artifacts

Source/build setup from `E:\POQI`:

```powershell
git clone https://github.com/sshi27/QuantumRouting.git results/qcast/QuantumRouting
git -C results/qcast/QuantumRouting checkout --detach 0a0251dd5f38eb1669ff6abe18ab83436ddbba18
# Portable Maven 3.9.9 ZIP and .sha512 came from:
# https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.9/
# Compare Get-FileHash -Algorithm SHA512 with the supplied checksum before extraction.
& results/qcast/tools/apache-maven-3.9.9/bin/mvn.cmd -B -f results/qcast/QuantumRouting/pom.xml '-Dmaven.repo.local=E:/POQI/results/qcast/m2' compile org.apache.maven.plugins:maven-dependency-plugin:3.8.1:build-classpath '-Dmdep.outputFile=E:/POQI/results/qcast/QuantumRouting/classpath.txt'
```

Maven cache, checkout, paper and all generated artifacts live under ignored
`results/qcast/`. The runner defaults to offline mode once dependencies are
cached; `--online` enables first-time dependency downloads. Use new output and
dedicated test temporary directories:

```powershell
.\.venv\Scripts\python.exe -B scripts/qcast_reference.py --output results/qcast/validation-03
$env:QCAST_VALIDATION_DIR = 'E:/POQI/results/qcast/validation-03'
.\.venv\Scripts\python.exe -B -m pytest tests/test_qcast_reference.py tests/test_pressure_policy.py -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/qcast-targeted
.\.venv\Scripts\python.exe -B -m pytest tests -q -o addopts= -p no:cacheprovider --basetemp E:/POQI/tmp/qcast-full
Remove-Item Env:QCAST_VALIDATION_DIR
```

The actual JVM/compiler commands, versions and SHA256 hashes are in the
[manifest](results/qcast/validation-03/manifest.json); full configurations,
allocations, channel identities, swap inputs and outcomes are in
[reference.json](results/qcast/validation-03/reference.json). The
[independent audit](results/qcast/validation-03/audit.json) recomputes metrics,
residual allocation and physical accounting. Ordinary pytest runs without
`QCAST_VALIDATION_DIR` explicitly skip native-artifact checks; they do not
claim a JVM run occurred.

The first run, `validation-01`, completed the JVM cases but failed in Python
when decoding Windows console output as UTF-8. Its failed manifest and output
were retained. Explicit JVM console encoding and tolerant log reading fixed
that postprocessing issue. `validation-02` passed the initial audit;
`validation-03` adds independently checked post-swap input/endpoint records.
No failed or zero-service physics cases were dropped.

## Remaining gates

No blocker remains to running this bounded reference. Unvalidated areas include
larger graph/tie behavior, general overlapping recovery, heterogeneous swaps,
distributional accuracy, fidelity/decoherence, classical message cost and
underlying trial duration/count. The current code reference is not asserted
to reproduce every paper algorithm detail or published figure.

A fair POQI performance comparison still requires the plan's explicit physical
opportunity scheduler, demand mapping, labelled persistence/service variants
and conservation tests. The current successful-pair Poisson streams cannot
be relabelled as matched raw attempt budgets. No adaptation, large sweep,
cross-policy ranking or memory advantage against Q-CAST is claimed here.

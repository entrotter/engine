# Account impact of an omitted historical oracle update

An agent developer needs more than identical receipts or a different price.
This actual bounded replay reads an existing Aave debt account on both owned
branches and shows the resulting borrowing-capacity and health differences.

| After the first 13 original transactions | Baseline | Skip transaction12 |
| --- | ---: | ---: |
| Total collateral, base units | 41049031017510 | 41175556915484 |
| Total debt, base units | 16199140199548 | 16219364581293 |
| Available borrowing, base units | 16845329769548 | 16926958735672 |
| Health factor, WAD | 2103240994573506125 | 2107093164381383462 |

The observed base unit is 100000000. Available borrowing differs by
81628966124 base units (USD816.28966124). Health differs by
3852169807877337 WAD units; both observed health values remain above one.
These are returned evaluations, not realized money, a new loan or a liquidation.
[Full sealed result](position.json) preserves every raw getter word, phase head,
code identity, configuration read and all original receipt/log bytes.

## Execution and source

The separate versioned [plan](../../tests/data/aave-account-prefix.json) uses
Ethereum block18999892, pinned hash/parent, through index12 and skip[12]. All13
baseline projected receipts exactly match their captured originals and the first13
of the earlier [native32 baseline](../aave-consumer-price/native-006/report.json).
The candidate executes12 original signed transactions and omits12, with no
invented signatures, funding, state or nonce repair. This new13 scope does not
replace the earlier32 evidence.

The [account source](account-source.json) retains a successful direct Pool
transaction at block18999884, its sender and receipt. No owner identity is inferred.
A preliminary discovery probe did not retain its block-qualified request bytes;
it is not treated as authenticated parent or four-phase execution evidence.

The [launch](launch.json) binds the plan and all23 image inputs to the actual
[immutable local image](worker-image.json), including all22 engine modules and
Dockerfile. It is default Docker execution, not a native fallback. One actual
attempt completes: trace92.565119s, host95.486630s, within unchanged150/180 caps.
[Terminal outcome](execution.json) records return0 and absent owned worker slot.
Existing Docker enforcement/cleanup tests are separate evidence; the terminal
slot check is not a new per-process/cgroup or OS-advisory scan.

All four initial/after price and account views have no errors. Initial full
six-word account values and heads match. Pool proxy code is2400bytes/SHA256
`bf8a408a1f5440c167d91fa2d972deb23bb4d809e8dd089009885ec88a826f88`
and is unchanged across phases. Pool's addresses-provider getter equals the fixed
historical provider; its price-oracle getter equals the observed Aave oracle in
every phase. This binds the returned account base unit to those returned
configuration views. Proxy code/returned addresses do not authenticate deployed
implementation or upstream state. Account data aggregates all reserves; the
branch comparison does not isolate WETH price as the sole cause.

## Reproduce and verify

After the normal image setup in the [engine README](../../README.md), set your
archive provider and execute:

```bash
PYTHONPATH=src python3 -m entrotter_engine trace-position tests/data/aave-account-prefix.json -o position.json
PYTHONPATH=src python3 tests_isolated/check_position_result.py position.json
```

The checker compares complete account/price records and all13 baseline/12
remaining signed outcomes with retained actual evidence. It ignores new runtime
and artifact IDs, not scientific values, source pins or recorded errors. Missing
archive state fails or remains explicitly unproven; no fixture substitutes.

[Local native suite](native-tests.log) passes379 tests/97.300s with zero skips on
final production source. This precedes a test-only export-state variable repair
and additional host-binding and stable-source comparator groups; [final15 targeted controls](position-controls.log)
pass8.395s. This is not a single local381-test run. The former full374 run had
one macOS diagnostic-client cleanup os_error; its unchanged focused check passes,
then the later full379 run passes. Cause remains unknown and the original failed
raw log is retained locally. New mocked controls do not prove actual cancellation.
The [legacy public33 controls](legacy-public-controls.log) remain passing.

Independent prelaunch review found a missing account-unit configuration binding.
Two fixed getters and unproven/null regression controls fix it before actual
execution. Inputs cannot choose another pool/provider/ABI/selector or callback.
There are52 fixed reads; ordinary/config/code reads cap at2s and the aggregate
account call at10s, always within the original remaining150s deadline. Output
uses the shared atomic quota. Initial prelaunch host setup failed before launch
because the harness used the wrong Dockerfile path; the failure is retained and
is not counted as an executed or restarted historical attempt.

The final same-image [Docker26 suite](docker-tests.log) passes with pinned host
Anvil1.8.3, including actual kernel/lifetime controls. The initial unpinned-host
run had three native-comparison failures, retained locally; no image/code/resource
change is attributed to the repair. Final wheel validates all22 current modules,
all26 RECORD entries, full UTF-8 README and an installed `-I` result reader/CLI
entrypoint. A prior pip call mistook inherited source egg-info for installation;
isolated `-I` pip fixes setup. Docs24/293 all pass after correcting one invalid
Pool page fragment, with no exclusions. [Verification scope](verification.json)
keeps these repairs and prior failures distinct.

Final publication review identified that the golden checker omitted stable
trace source/assumptions. It now compares the complete nested trace except
runtime/artifact ID, with an offline resealed-source regression; actual receipt
and account results are unchanged. No new EVM execution was needed.

Current-head CI, final publication review, independent human main approval,
coordinator promotion, Pages and submission remain separate gates. No fresh
browser/model/market evaluation, signed consumer action, profit, whole-block/
state-root/opcode equivalence or complete G1 is claimed.

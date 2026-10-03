# Aave price reads after an omitted oracle update

An unchanged receipt does not imply unchanged state for another contract. In this
owned historical replay, the remaining31 transactions retain their gas/status/
logs, while Aave's WETH price getter observes a different value when transaction12
is omitted. This is read-only consumer evidence, not a signed consumer action.

## Observed result

| Owned phase | Producer answer | Aave `getAssetPrice(WETH)` |
| --- | ---: | ---: |
| Baseline before | 257082415000 | 257082415000 |
| Baseline after | 256292441874 | 256292441874 |
| Candidate before | 257082415000 | 257082415000 |
| Candidate after, skip12 | 257082415000 | 257082415000 |

All four [consumer observations](native-006/consumer-observations.json) retain
exact one-word ABI returns and decoded values. `getSourceOfAsset(WETH)` is
`0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419` throughout; `BASE_CURRENCY()` is
the zero address and `BASE_CURRENCY_UNIT()` is100000000. Observed code is nonempty
and stable across these phases: Aave oracle3405 bytes/SHA256
`dc8079e555204e0b2d7dc8382d6ebd71901f0b43e5940463e22b75b810a37728`,
Chainlink proxy9571 bytes/SHA256
`ed698309290de3517c7201fcad9a9dbd4b8cde4a72c9add23129201f299c6f2b`.
These are returned-code identities, not authenticated deployment proofs.

[Producer observations](native-006/observations.json) retain original heads and
five-word round data. Initial heads/getters match; only the baseline advances
the round and answer. [Full report](native-006/report.json), SHA256
`2e4cc3966185ed92f40b3507a397269ad44d098a65b8bf2dcb57b331f33a2d79`,
has all32 projected baseline receipts byte-equal to captured originals and the
prior successful baseline. Candidate skips12 and executes31;19 later receipts
differ only by transactionIndex-1 and cumulativeGasUsed-336752. All other receipt
fields remain equal. Original signatures, source/header/state handling and bounds are
unchanged from [native005](../trace-parent-cache/native-005/report.json).
The [offline SDK and Node viewer read](independent/sdk-viewer-reader.json)
checks all32 typed receipt outcomes and retains12 identical/1 omitted/19
structural/0 execution/0 unavailable classifications on unchanged SDKee and
viewerb1cf. This is parsing/classification, not a rendered browser check or
validation of the separate Aave getter records.

The [plan](native-006/plan.json) covers the first32 of181 signed transactions
from Ethereum block18999892, parent18999891. Native006 completed once:
report132.703057s, native132.738311s, host132.865456s. The original shared trace
limit is150s, child180s, host190s, host cleanup10s. Six extra fixed read-only
queries per phase mean24 total, each capped at2s within the same deadline.
The observer accepts at most64KiB of decoded code and writes at most64KiB of
consumer evidence. These are validation/output limits: the unchanged RPC
transport can read up to4MiB plus one overflow byte before rejecting a response.
The frozen readiness field `consumer_code_response_bytes` refers to accepted
code, not a64KiB transport download cap.
[Result](native-006/result.json), [host outcome](native-006/host-result.json)
and [independent raw review](independent/native-006-execution-review.json)
record no primary, observation, evidence or cleanup failures. Two owned Anvil
nodes and one cache close, including cache pipes; fresh root PID/group/port
checks pass. Aggregate cache counters include7 errors of unknown cause; they
do not identify provider failures or contradict the recorded completed getters.

## Inspect and reproduce offline controls

From this repository checkout and the existing locked quality environment,
Python3.11+ can run the portable controls without an archive provider, installed
Anvil or model call. The locked `certifi` package is needed for importing the
host helper; the offline command does not use it to contact a provider:

```bash
PYTHONPATH=src:evidence/aave-consumer-price/harness .venv/bin/python -m unittest discover -s evidence/aave-consumer-price/harness -p 'test_*.py' -v
```

These33 controls exercise the real observation/decoding/classification and
instrumented entrypoint code with controlled transport/session substitutions:
wrong source/unit/currency/price, empty/changed code, malformed/oversized ABI,
duplicate phases, finite deadlines, cancellation before/after views and during
snapshot/cache startup, primary failure preservation and finite diagnostics.
They start no native services/processes or archive/HTTP connections. A fake-owner
cleanup fixture does perform read-only OS/group and loopback port1 probes; that
test is not real native ownership/closure evidence. Mandatory quality CI runs
this public-layout command; current-head CI remains pending until published.

The [observer](harness/consumer_observer.py) and [entrypoint](harness/native_runner.py)
are exact reviewed research-source copies, outside the shipped engine modules.
The standard `trace-run` command exports the unchanged trace report, not these
extra getter records. The host-bound archived instrumentation remains private;
its frozen [prelaunch review](independent/prelaunch-review.json) and
[readiness](native-006/readiness.json) are provenance, not runnable public paths.
The normal native trace can be attempted with the portable plan:

```bash
export ENTROTTER_RPC_URL='https://YOUR_ARCHIVE_PROVIDER'
PYTHONPATH=src python3 -m entrotter_engine trace-run evidence/aave-consumer-price/native-006/plan.json --native -o prefix-report.json
```

That separate command requires Foundry1.8.3 Anvil on PATH and a provider serving
the pinned state; it can fail and does not recreate the additional observations.
Do not compare a fresh report's runtime/artifact ID to a frozen result as if they
were deterministic timing evidence.

## Retained failures, references and limits

[Fix review](preparation/review-fix-summary.json) records the private watchdog
delivery correction: cancellation derives from BaseException so RPC transport
normalization cannot swallow it. Ordinary failures remain finite diagnostics;
cleanup completes before terminal evidence handling. Source/state/replay controls
and25 production files at198139f remain unchanged. Before-fix failures, a partial
33-test run with one test-only injection bug, and the affected8-test pass remain
in preparation logs; none is relabeled a clean aggregate pass. Public-layout
verification and current CI are separate results.

An initial [host-import setup failure](independent/host-import-setup-failure.json)
terminated before output creation or child launch; adding `PYTHONPATH=src` to the
invoking environment resolved it. The subsequent actual session completed once.
There was no restart after an observation timeout. Earlier native001–005 records
and their failed runs remain unchanged. This experiment does not prove speed or
the causes of earlier timeouts.

The [historical address-book metadata](references/historical-reference-summary.json)
points to the [January4 primary source](https://raw.githubusercontent.com/aave-dao/aave-address-book/575eac6d595d5d15ba5e6ca9192a2f2a5c719022/src/AaveV3Ethereum.sol).
Current source is [reference metadata only](references/current-reference-manifest.json);
its WETH source differs from the historical proxy. Neither source authenticates
the fork state. Current AaveOracle code is BUSL-1.1: no third-party source or
license file is vendored or relicensed here. See the
[official oracle API](https://www.aave.com/docs/aave-v3/smart-contracts/oracles)
for getter semantics.

[Copy provenance](provenance.json) binds original/public bytes and local-path-only
redactions. Private checksums refer to original records; redacted public copies
have their own listed hashes. No provider credentials, keys or private contacts
are published. This native32-of181 case is not default Docker execution,
full-block/state-root/opcode equivalence, deployed-code/provider authentication,
a signed consumer transaction, loan/liquidation/trade, agent performance, profit
or complete G1. Human approval, main integration, Pages and submission remain
separate gates.

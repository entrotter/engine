# Supported owned consumer observations: local evidence

This candidate adds `trace-observe --native` and the trusted Python
`consumer_observations.run_trace_observed_native` API. A separate sealed
observation-version0.1.0 wrapper retains the original trace report, source/report
artifact binding and four fixed Aave/WETH view phases. Normal trace-plan/results,
default worker and HTTP envelopes remain unchanged. Source decoding is dynamic;
unsupported code/ABI/source/currency/unit remains explicit and unproven.

The final plain native suite passes349 tests80.699s with0 skips. All60 prelaunch
source/test/doc/policy/runner bindings remain unchanged until terminal. This is
one authorized retry: the initial349-test run fails205.173s with one failure and
one error in unchanged diagnostic cleanup controls. Both logs are retained. The
intermediate instrumented repeat of just those two methods passes3.253s; it does
not establish the original cause. No runtime/test fix, signal instrumentation,
budget increase or archive call was applied for the full retry. Durations do not
support a speed or causal-resolution claim.

Six real pinned Anvil1.8.3 methods cover a signed synthetic oracle update20 and
omission10, actual signed consumer reversion, zero price difference without
omission, missing Aave code, CLI export, SIGTERM during branch views and sealing
interruption after owned cleanup. Source-only synthetic adapters/genesis funding
are explicit parent setup. Replay makes no state/nonce/signature repair. Twenty
unit methods check ABI/content/source/head/time binding, bounds, finite hostile
errors, actual RPC stop propagation, caller admission and export limits.

The26-source full Bandit scan retains all25 exact prior findings/rationales with
no skips/errors. Lint/format/mypy pass. Current wheel010 contains21 modules with
bytes identical to source; wheel004 is earlier pre-future-timestamp evidence.
Wheel binaries are not vendored here; their original SHA256 and module digests
are preserved in the readiness and wheel records.

## Records and provenance

- [Summary](summary.json) and [copy manifest](provenance.json).
- [Independent source/local-test/security/wheel review](independent/source-review.json),
  original SHA256 `02f1115a17700310d2c39e3ead4f0529ec054773beb2bad910618187c975eb96`.
- [Final checkpoint](author/final-checkpoint-011.json),
  [full retry prelaunch](author/prelaunch-full-009.json),
  [unchanged600s runner](author/full-native-runner-009.py),
  [full retry log](author/full-native-009.log) and [terminal](author/full-native-009-terminal.json).
- [Initial failed full log](author/full-native-007.log),
  [initial terminal](author/full-native-007-terminal.json),
  [focused instrumented result](author/diagnostic-reproduction-008.json) and
  [focused log](author/diagnostic-reproduction-008.log).
- [Final synthetic setup and signed original bytes](author/full-native-009-evidence/synthetic-source.json),
  [adverse paired wrapper](author/full-native-009-evidence/test_real_paired_receipts_price_effect_and_exact_original_source-wrapper.json),
  [zero-difference wrapper](author/full-native-009-evidence/test_real_no_omission_reads_complete_with_zero_price_difference-wrapper.json),
  [unproven missing-code wrapper](author/full-native-009-evidence/test_actual_missing_aave_code_reads_unproven_without_replay_fallback-wrapper.json)
  and [owned closure records](author/full-native-009-evidence/cleanup.json).
- [Actual full scanner output](author/bandit-006.json),
  [retained-finding evaluation](author/security-evaluation-006.json),
  [current wheel proof](author/wheel-proof-010.json).

The54 manifest copies comprise46 byte-identical files and eight path-only
redactions. [sanitize.py](sanitize.py) replaces only the actual local workspace
root with `/workspace/Entrotter`. Every original local SHA256 and public-copy
SHA256 is separate in the manifest. Raw originals and earlier failures remain
immutable. Local `.quality` and watchdog paths in historical metadata are
provenance, not contributor prerequisites. No signing keys, private provider URL,
third-party source bundle, contact or credential is included.

## Contributor commands

With the repository's locked quality environment and pinned Anvil1.8.3 on `PATH`,
run the current source controls (these regenerate disposable synthetic evidence):

```sh
PYTHONPATH=src:tests python -m unittest test_consumer_observations test_consumer_observations_evm -v
python -m build --wheel --no-isolation
```

To replay a contributor-selected original trace plan against an explicitly
configured read-only archive provider, use the supported command:

```sh
PYTHONPATH=src python -m entrotter_engine trace-observe plan.json --native -o observed-trace.json
```

The provider uses the existing `ENTROTTER_RPC_URL` configuration; keep its value
private. `--native` is mandatory. Unlike the prior private research observer,
this command exports its four fixed view phases inside the sealed wrapper.
Read an exported wrapper offline through
`consumer_observations.load_observed_trace("observed-trace.json")`.

## Scope and pending gates

At this initial package's publication, the supported command had not executed
the historical32-input case. The later [supported32-input execution](historical-32/README.md)
records that actual run separately; prior native006 research remains distinct.
The synthetic plan in this package
requires its disposable source setup; its local loopback endpoint is closed and
is not an independently available archive service.

The150s signal guard covers replay and owned cleanup, ending before wrapper
sealing/export. It is not a whole-command CPU/RSS sandbox. Fixed views accept
code/observation data up to64KiB; unchanged RPC transport reads4MiB+1 and refuses
responses above4MiB. Complete reads and raw price difference remain separate
from baseline receipt verification. Round consistency/future-time sanity is not
a maximum-age freshness policy. No provider authentication, signed historical
consumer strategy, benefit/profit, full-block/root/opcode proof or complete G1
claim follows. Public-package review, exact-head mandatory CI and protected-main
human approval remain separate pending gates; no merge/deployment is claimed.

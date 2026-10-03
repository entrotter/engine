# Supported CLI: original32-input Aave price replay

The actual `trace-observe --native` CLI module at enginee9d629e executes the first32
of181 original signed transactions in Ethereum block18999892, excluding index12
from its candidate branch. It exports the [strict sealed wrapper](observed-trace.json),
not just the earlier private research observer's output. A passive Python lifecycle
profile records owned objects without replacing production functions, adding RPC
calls, changing state/transactions or extending the original150s replay deadline.
This was one actual attempt; no narrower prefix or retry replaced it.

All32 complete baseline receipts equal the originals. Candidate executes31; its
later19 receipts differ only by transaction index minus1 and cumulative gas
minus336752. All other receipt fields, source inputs and complete branch outcomes
match the prior native006 record. Four raw ABI views show Aave WETH price equals
its observed producer answer: baseline257082415000 before and256292441874 after;
candidate remains257082415000. USD unit is100000000; the raw after-price difference
789973126 is not a return or profit metric. Both initial heads/getters match;
oracle/source code identities stay stable and nonempty.

Actual replay127.599511s, CLI127.803665s and host127.921839s fit the unchanged
150s product replay/cleanup cap. These instrumented observations are not a speed
benchmark. Owned2Anvil guardians and one cache are reaped with groups, ports and
pipes closed; independent host probes confirm all3groups/ports absent. Cache1879
requests/970 upstream/903 hits/964 entries/2647997 bytes/6 uncached/0 refused;
6 aggregate errors retain unknown cause. Native execution has no whole-process
CPU/RSS sandbox. No default Docker32, signed consumer action, strategy benefit,
provider/deployed-code authenticity, full-block/root/opcode or complete G1 claim
follows from this partial read-only experiment.

## Inspect without a provider

From this repository checkout:

```sh
PYTHONPATH=src python3 - <<'PY'
from entrotter_engine.consumer_observations import load_observed_trace
from entrotter_engine.trace import write_trace
observed = load_observed_trace("evidence/owned-consumer-observations/historical-32/observed-trace.json")
print(observed["classification"])
write_trace(observed["trace_report"], "transaction-replay.json")
PY
```

The strict engine loader validates the entire observation wrapper. Existing
SDK/viewer trace readers can inspect the exported nested report; they do not
validate its additional price views. Export remains subject to the normal quota.
To attempt the same original plan with pinned Anvil1.8.3 and your explicitly
configured read-only archive provider:

```sh
export ENTROTTER_RPC_URL='https://YOUR_ARCHIVE_PROVIDER'
PYTHONPATH=src python3 -m entrotter_engine trace-observe evidence/aave-consumer-price/native-006/plan.json --native -o observed-trace.json
```

Provider availability/latency can prevent replay. No source-state repair, nonce
repair, future simulation or fixture substitution is performed.

## Exact records

- [Fixed original plan](plan.json), [environment](environment.json),
  [final readiness](readiness.json), [CLI module observer](cli-child.py) and
  [owned host runner](run.py).
- [Raw CLI stdout](stdout.log), [stderr](stderr.log), [child terminal](child-terminal.json),
  [host terminal](host-terminal.json) and [ownership ledger](owned-ledger.json).
- [Complete root result verification](verified-result.json) and
  [verification source](verify-result.py).
- [Initial prelaunch findings](independent-prelaunch-review.json),
  [final prelaunch review](independent-prelaunch-final-review.json),
  [five fault controls](test_harness.py) and [actual fault output](fault-controls.log).
- [Independent execution review](independent-execution-review.json) and
  [its full source](independent-execution-review.py).
- [Exacte9 CI root review](root-ci-e9-review.json) and
  [independent CI review](child-ci-e9-review.json), with
  [root verification source](root-ci-e9-review.py) and
  [independent verification source](child-ci-e9-review.py); all8 original required runs
  pass: [native356/0skips](https://github.com/entrotter/engine/actions/runs/37034024850),
  [units356/40Anvil skips each](https://github.com/entrotter/engine/actions/runs/37034024917),
  [isolated25/default1+4/image audits](https://github.com/entrotter/engine/actions/runs/37034024674),
  [quality](https://github.com/entrotter/engine/actions/runs/37034024700) and
  [21documents/222links](https://github.com/entrotter/engine/actions/runs/37034024671).
  Full raw review binds26 production sources/25 retained findings/21 wheel modules,
  42 Python/31 OS/1126 signed Cargo identities with0 reported advisories. The172
  non-Cargo entries and non-exported database/tool binaries remain explicit audit
  limits. CI's default1/four cases are separate from this native32 run.
- [Copy provenance](provenance.json). Only the actual workspace prefix is replaced
  with `$WORKSPACE_ROOT`; original/public SHA256 values are separate. Historical
  `.quality` paths and normalized runner/binary locations are provenance rather
  than contributor prerequisites. The initial readiness37eb raw bytes were
  overwritten during preparation before the review message arrived; its digest/
  bindings remain in the initial review. They are not reconstructed or claimed
  as retained originals. [Pre-final readiness0877](readiness-pre-final.json) and
  final57d335 original bindings are retained. Preparation findings were fixed
  before the only archive attempt.

Protected-main human approval, deployment and formal submission remain separate.
This record establishes a usable supported-command reproduction milestone.

# Synthetic signed oracle dependency and provider-state coverage

This candidate starts from tested engine935558a/PR31. Its only production
change is one explanatory report assumption. Signed execution, source/header
binding, deferred pool admission, EVM validity and all bounds remain unchanged.
Four new real native regressions pass; the full252-test suite passes in37.568s,
with0failures/errors/skips. One new direct bounded-image protocol case awaits CI.
This is synthetic causal receipt evidence, not historical price/oracle service,
profit, model advantage, whole-block/end-state truth or deployment proof.

## Source setup and observed causal effect

The [frozen inputs](../../tests/data/canonical-local-oracle-inputs.json) contain
only disposable public signed transactions, never keys. Two real signed CREATE
transactions deploy the synthetic oracle and consumer before the target block.
Only the original source genesis receives1ETH per sender; replay forks its exact
pinned parent without code/balance/nonce overrides or signature replacement.
The oracle begins with storage value10. The original signed update writes20,
then a separate sender's consumer calls the oracle in the same target block.
The consumer requires20 and emits one LOG0 word20; otherwise it reverts.

The [fresh native report](native-oracle-prefix.json) exactly matches both original
projected receipts: status1/1, gas26167/26438, cumulative gas26167/52605,
and logs0/1 with the consumer word20. Omitting the update preserves the original
consumer signature/hash and yields an executed **reverted** receipt, gas25808,
with no logs. Status, gas/cumulative gas, transaction index, bloom and logs differ.
The source remains at20 with nonces3/1. No independent nonce conflict masks this
dependency, and no future/external oracle response or token-profit interpretation
is invented.

## Real provider faults, without fallback

A read-only loopback proxy forwards the same synthetic source. Its
[normal control](native-provider-control.json) verifies the original receipts.
Optional Anvil node/account fast paths are unsupported identically in all arms.
The [native test summary](native-suite-summary.json) records actual forwarded
method counts, injected denial counts, nine successful guardian closures and
five closed proxy threads/ports.

| Actual injected fault | Checked result at public native entrypoint |
| --- | --- |
| Missing pinned parent header | Explicit `ExecutionError`, no replay report |
| Missing account code or balance | Explicit `ExecutionError`, no fixture substitution or report |
| Missing storage during mining | [Integrity-valid unverified report](native-missing-storage.json); baseline `not_mined/not_mined`, candidate `skipped/not_mined`, no receipts |

The pinned Foundry executor skips database/execution errors during mining
([account access](https://raw.githubusercontent.com/foundry-rs/foundry/cae51ad458f6abb64852b7709eb784352429825d/crates/anvil/src/eth/backend/executor.rs) (source lines 610–617),
[execution errors](https://raw.githubusercontent.com/foundry-rs/foundry/cae51ad458f6abb64852b7709eb784352429825d/crates/anvil/src/eth/backend/executor.rs) (source lines 717–726)).
Thus `evm_mine` need not return an RPC error. The report honestly remains
unverified. **Receipt absence alone cannot identify the cause or attest parent
state.** Known fault injection is test evidence, not an inferred report claim.
Syntactically valid incorrect provider state remains outside these refusal checks.
There is no fixture-state/oracle-response substitution or state repair.

## Checks and provenance

Full23-source lint/format/mypy passes. The full scanner retains all23 expected
findings/rationales with0skips/errors; only trace.py's source digest changes.
The stale-source gate [failed before refresh](security-before-refresh.log),
then [passed](security.log). All42 exact locked Python packages have0reported
advisories. See [summary and source hashes](summary.json),
[Bandit raw report](bandit.json), [dependency report](dependencies.json) and
[public-copy provenance](public-copy-provenance.json).

An initial249-test attempt failed on the new test's incorrect `ExecutionError`
import ([retained failure](native-suite-import-failure.log)). Correcting the
test import produced [four focused passes](focused.log) and the
[fresh required252-test pass](native-suite.log). Existing oracle behavior already
worked; these are added coverage, not a claimed failing-before product fix.
Local Docker/VM startup, archive/model/holdout/media runs and upstream writes
did not occur. Direct image/protocol tests and host default dispatch/lifecycle
checks have separate scopes; the existing historical image/native gates remain.

The [prior investigation](prior-investigation.json) and contemporaneous
[root direction review](root-direction-review.json) are immutable historical
records. The [original initial six-node observations](prior-initial-observations.json)
and [original report](prior-initial-oracle-report.json) survive, along with the
[initial diagnostic setup failure](diagnostic-setup-failure.log) and cleanup.
An ignored fixture generator accidentally overwrote the original nine-node
followup's full observations JSON/report. Those original byte sequences are
unavailable; their prior hashes and aggregate
[followup log](prior-followup-probe.log) survive. This is explicitly recorded in
[evidence handling](evidence-handling.json); fresh fixture-generation or native
results are never substituted under the old hashes. Generator outputs now have
distinct paths, and the native evidence runner refuses an existing destination.
Public copies redact absolute personal workspace paths; ignored raw copies remain
except the two disclosed lost files.

The [independent source/privacy/evidence review](independent-review.json) passed
with no remaining actionable findings. It also accepted the three fresh reports
through unchanged SDKee and viewerb7 offline validators; this is no new rendered
browser or EVM proof. Original pre-publication hashes and evidence-loss scope
remain preserved. All eight exact-head CI checks remain pending. Human protected-main approval, merging/deployment and the overall
G1–G5 goal are separate and remain open.

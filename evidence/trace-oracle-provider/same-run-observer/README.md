# Bounded observation of a separate failure diagnostic

The earlier exact-head [aac isolated run](https://github.com/entrotter/engine/actions/runs/36913460373)
passed25Docker tests and the normal first-prefix replay, then failed the mandatory
four-prefix gate. Its original four receipts matched, but candidate transaction2
was `not_mined`. A **later separate diagnostic** completed normally. The original
cause remains unknown; seven required checks passed, isolated failed, and later
image/native advisory stages did not run. [Original reports and partial proof](prior-aac-ci/root-partial-verification.json)
retain those exact observations. Neither this package nor a healthy diagnostic
substitutes for a mandatory normal default-worker pass.

Only the existing trusted failure-only helper changes. It still calls unchanged
`execute_request` on the exact `encode_trace_request` envelope, reserves the same
fixed daemon worker slot with a unique owner, and preserves container quotas,
archive bridge, one shared150-second trace budget, entrypoint180s, host190s,
and16KiB diagnostic output. The mandatory normal one/four-prefix workflow bodies
and all23production sources remain byte-identical to aac. This adds no public
runtime command, arbitrary executable, environment selector, state repair or retry.

The helper substitutes a fixed observed guardian **within its own invocation**.
It reuses original `supervise` owner-pipe, signal, lifetime and terminate/kill
behavior, captures both child streams, and sets only `RUST_LOG=backend`.
[Pinned Anvil tracing initialization](https://raw.githubusercontent.com/foundry-rs/foundry/cae51ad458f6abb64852b7709eb784352429825d/crates/anvil/src/lib.rs) (source lines 471–506)
accepts this target filter; the controlled native probe confirms backend events
without blanket HTTP trace flooding. Each finite row binds the actual worker
request SHA, baseline/candidate order and captured original transaction indices.
Unknown, contradictory or unbound rows are discarded. Secondary observer errors
never overwrite the original replay failure/status.

Only fixed event/error enums, integer counters and closure/completeness metadata
are emitted. No child log text, URL, error message, args, traceback or credentials
are returned. The parser scans at most131072total bytes with8192-byte lines and
65535counter saturation, continues draining excess without accumulating it, and
reports EOF, scan cap, overlong/partial lines and reader errors. Missing events
are not evidence of no error, especially after truncation/incomplete drain. Logs
are unauthenticated observations, not provider/state or EVM truth. Reader-start
failure and collector timeouts close descriptors and the owned child/session;
foreign sessions/containers remain outside cleanup.

[The frozen004 probe](frozen/probe.py) runs the actual diagnostic embedded program
and unchanged worker protocol against disposable synthetic signed oracle inputs.
It preserves the [exact request bytes](results/worker-request.json) before launch
and [unobserved original report](results/unobserved-original-report.json).
Observed control preserves every source/plan/baseline/candidate receipt value;
its original baseline verifies and omission reverts the dependent consumer.
Injected read-only missing storage produces unverified `not_mined` receipts and
same-invocation `execution_skip` counters2/1, bound to original indices0,1 /1.
[Finite observations](results/finite-observations.json) record full EOF/no cap,
raw drained bytes6601/4868(control),6100/4269(fault), seven node exits/ports,
eight readers and two proxy listener/handler/port closures. Source oracle20 and
sender nonces3/1 remain unchanged. No keys are retained. These are native
synthetic cases, not Docker/default-host/historical observer proof or profit.

Fourteen focused observer tests passed in3.643s against the [preserved003 test
snapshot](frozen/test_trace_observer-003.py), followed by one additive final-file collector-owned descendant test
in3.113s. The latter actually leaves stdout and a listening port in a forked
child, then verifies the collector's deadline, finite timeout, descriptor close
and its own descendant port cleanup. Fifteen prior diagnostic tests pass in0.739s.
Tests cover real embedded exit7, owner EOF/lifetime, flood/privacy, reader-start
failure, unsafe binding and primary replay error preservation. [Initial import
harness failure](checks/initial-import-harness-failure.log) is retained; module
registry registration fixed `inspect.getsource` in the test harness. It was not
a reproduced production replay defect. No unchanged broad native/image suite
was rerun locally; new-head required CI remains pending.

[Earlier prototype review](prototype-review.json) applies only to002. The first
001six-test exact source bytes were not preserved; ordered002unit binding and
003's missing independent raw unobserved report remain explicitly distinct.
004 closes that raw comparison gap with prelaunch [source hashes](readiness.json)
for23production files, oracle helper, guardian, fixture, workflow and final tests.
[Copy/redaction provenance](copy-provenance.json) preserves original hashes;
only the initial failed test log's personal paths are redacted. Existing oracle
nine-node raw evidence loss stays disclosed in the enclosing evidence. Single
native timing observations are not speed or benchmark claims.

[Final independent source/protocol/privacy/evidence review](independent-review.json)
verified33frozen bindings, full raw report equality, finite fault events/cleanup
and unchanged SDKee/siteb7 offline report acceptance with no remaining actionable
finding. Its scope excludes GitHub human approval, Docker/kernel controls and
new-head CI success. [Summary](summary.json) records current readiness. No local
Docker/VM, archive/model/holdout/media operation, upstream writes, protected merge,
deployment or submission occurred. Overall goal remains active.

[Final package review](package-review.json) independently verified the preceding
30public files/27copy bindings, earlier14-test bytes and the additive collector
regression with no remaining finding. Exact review SHA256 is
`8ef32d8bcb323ce5b2dca212fa42d64d7428dacd35b9beb2a5eae3e83057a803`;
the copy is byte-identical to coordination `.quality/oracle-integration/`
`root-integrated-observer-package-review.json`. The original package readiness
remains a pre-addendum observation; this review file and this paragraph were
added afterward. New-head CI remains pending.

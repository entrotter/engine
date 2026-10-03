# Bounded admission and signed base remediation

The supported native observation CLI remains the same fixed Aave/WETH read-only
profile, shared150-second trace limit and separate strict wrapper. This follow-up
preserves existing cache/worker/HTTP contracts and every mandatory gate.

A real HTTP control fills all four handlers, accepts a fifth socket and releases
one handler20ms later. The old nonblocking admission resets that read; bounded
admission returns the original response with its fresh request ID, one upstream
call and at most four active handlers. The accepting thread waits at most100ms
or the original remaining deadline. Sustained pressure is still refused, and the
listen backlog is explicitly four. No extra active handler, cache/key limit,
method or execution budget is added. See the [before](cache/before-real-http.log),
[after](cache/after-real-http.log), [26 controls](cache/parent-cache-suite.log) and
[independent source review](cache/child-source-review.json). The original Linux
nonce rejection had13 refused handlers; its cause is not established by this
macOS reproduction. [Original failed CI](previous-ci/evm-9a68-failed.log) is retained.

The prior built worker inventory reports three vulnerabilities in py3-pip-wheel
26.2.1-r1. Docker now pins the signed Python base89281daa; its amd64 and arm64
manifests/configs, full inventories, signature and fresh scanner metadata are in
[base evidence](base/summary.json). Both platforms retain all26 prior package names
and inventory five additions:31 packages/zero reported findings with the unchanged
all-findings policy. py3-pip-wheel is26.2.1-r2. This is remote base evidence, not an
audit of the newly built Entrotter worker or proof of Linux Anvil compatibility.
The [prior built worker findings](previous-ci/old-worker-packages.json) remain
historical; current exact-head mandatory isolated CI is still required.

| Local checkpoint | Result | Scope |
| --- | --- | --- |
| [Original full352](native/full-native-001.log) | One cleanup assertion failure | Secondary cause not recorded; retained |
| [Prefinal full353](native/full-native-002.log) | 353 pass/82.985s | Before final test-helper rescue correction |
| [Final full354](native/full-native-003.log) | 354 pass/79.788s, zero skips | Anvil1.8.3/macOS/Python3.13; no archive/model call |

The original immediate-exit output-limit test now preserves four finite diagnostic
fields on failure. A live overflowing child is killed/reaped with stdout closed.
Independent review caught a test assertion that could skip rescue; try/finally
and an actual false-cleanup-success fault regression fix that gap. All original
cleanup assertions remain. [Seventeen diagnostic controls](cache/diagnostic-controls-003.log)
and [independent final review](cache/child-diagnostic-final-review.json) pass. The
354 success and a focused pass do not retroactively identify the352 failure.

[Root final review](cache/root-final-local-review.json) binds all75 prelaunch
inputs, the original terminal/log, all eight owned replay cleanup records, three
strict synthetic wrappers and21 wheel module bytes. Every owned node/cache/source/
proxy closure check passes; cache admission refusals are zero in these synthetic
runs. These are not the supported historical32 execution. CPU/RSS whole-process
bounds, provider authenticity, signed consumer strategy/profit and full-block
reconstruction are not established. Native cleanup/default isolated worker limits
remain those documented in SECURITY.md. Production quality retains26 scanned
sources and all25 explicitly reviewed findings; no suppression or gate is added.

[Provenance](provenance.json) distinguishes original and public hashes. Copies
change only the workspace-root path where necessary. Original summary hashes
still describe original files; only selected base evidence is vendored, not all
private helpers/database bytes. No binaries or credentials are published. Docs
and this evidence are added after the frozen native execution. New exact-head
Linux/worker CI, independent human main approval, deployment and historical32
supported-command verification remain separate; no formal submission is claimed.

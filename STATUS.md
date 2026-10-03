# Engine candidate status

## 2026-10-03 — Fixed base-image advisory candidate, CI pending

The Dockerfile now selects a signature-verified immutable public Chainguard
Python base with pip bootstrap wheel26.2.1-r2. This addresses the three observed
CVE-2026-97687/97689/97688 findings without suppressing any advisory. Full remote
amd64 and arm64 base scans use pinned Trivy0.74.0, a fresh database and unchanged
all-severity/required-inventory checks; each inventories31 OS packages with zero
detected findings. All26 former package names remain, with five additional
Brotli/OpenSSL libraries and a newer Python3.14 micro revision. Existing Cosign
3.1.3 identity/issuer requirements pass for the exact new index digest.

This is remote base evidence, not an executed built-worker result. The current
image/source binding, Anvil/worker compatibility, complete replay and full native
security gates still require new-head CI. Old image and failure reports remain
immutable; no merge, deployment or historical replay cause is inferred.

## 2026-10-02 — Changed-source native32-prefix evidence, publication prepared

After independent source/package and frozen prelaunch review, one root-owned
instrumented native replay completes the original32 signed transactions of
block18999892 and candidate skip[12]. All32 complete projected baseline receipts
match originals and the prior baseline. The candidate executes31 transactions;
their gas/status/logs/bloom/identities remain unchanged, with later indices
shifted by one and cumulative gas reduced by exactly336752 (the omitted gas).
Initial heads and getter bytes match. The baseline feed answer changes from
257082415000 to256292441874 with a round increment; the candidate retains the
parent answer. All four getter phases have zero errors. This establishes
producer update omission, without an identified dependent consumer or profit.

Native elapsed time is125.358258s and report runtime125.330162s. Cache counters
are1871 requests,966 upstream reads,899 hits,960 entries/2640492 bytes,6 uncached
responses,6 aggregate errors and0 handler refusals; these errors do not identify
a provider cause. Two owned Anvil nodes and one separate cache child close with
PID/group/port/pipe checks. All earlier failed experiments and source bindings
remain immutable. One success after changed source does not establish speed or
timeout causality. This is32 of181 transactions, not full-block/state-root/opcode
equivalence or authenticated provider state; native has no default Docker
CPU/RSS/PID quota proof. Published SDKee and viewerb7 accept the report offline;
there is no fresh rendered-browser or Pages check.

See [public raw evidence and copy provenance](evidence/trace-parent-cache/README.md).
Final source323-test/security/wheel and actual native evidence independent
reviews pass. A material draft PR and all eight exact-head checks are pending;
no merge, deployment, integration pin change or broader G1 completion is claimed.

## 2026-10-02 — Per-key parent-read concurrency, local candidate

The serialized cache candidate's frozen full suite passed314 tests/123.790s with
zero skips, and independent source/security/wheel review passed. Its one owned
historical32-transaction experiment then failed during baseline mining at
150.157490s. The initial latestRoundData getter also failed; no initial price,
baseline receipts, candidate or final protocol report is asserted. Captured
inputs remain byte-identical to the prior experiment. Aggregate cache counters
show739 upstream reads and zero hits; all owned Anvil/cache processes and ports
close. These observations do not identify the cause of the mining timeout.

The current local change removes global serialization of upstream I/O. Up to
four eligible keys coalesce successful cached results; unrelated keys and
uncached receipt/volatile reads progress independently. All original limits,
method rules, raw JSON tokens, ownership and shared deadlines remain unchanged.
Two actual loopback concurrency regressions fail before the change (4.553s)
and pass after it (1.029s). An expanded23-test run retains one erroneous header
fixture failure; correcting that fixture and testing owner cancellation passes
two focused controls (1.024s). Independent actual-helper tests also verify
four-key concurrency/refusal, duplicate-key/receipt behavior, owner-error wakeup
and complete child/group/port/pipe closure. The frozen full323-test run passes
in75.836s with zero skips; all25 production lint/type/security checks retain
all25 reviewed findings. A fresh wheel matches all20 modules, and21 declared
image inputs match source; no actual image was started. Final independent
source/package review and publication were pending at that checkpoint. Prior314 proof and
failed historical experiment remain separate from this new candidate. No new
archive execution or Docker/CI run occurred before that source-review checkpoint;
the later native experiment is reported separately above.

## 2026-10-02 — Experiment-local parent read cache, local candidate

The trace-only bridge shares successful exact-parent-hash state responses and
hash-checked parent headers between independent original/candidate forks. It
preserves result JSON bytes with the current request ID, fixed read methods,
the shared150-second deadline and default resource/ownership guards. It uses a
bounded loopback child and in-memory cache; no disk/HOME/state repair is added.

The first owned synthetic run failed at startup because optional JSON-RPC
parameters and unsupported-method response IDs were mishandled. That frozen
failure is retained separately. After correcting those envelope cases, the same
signed oracle update/consumer omission case preserves complete source and both
receipt projections, reducing actual upstream state reads from29 to16 (15 cache
hits including two header reads). Seven owned nodes and two proxies close, with
zero added reader threads left. Fourteen initial loopback tests pass against the
stdin transport. The first full suite retains306 tests/662.692s with two actual
unmined-receipt forwarding errors and a600-second build-watchdog failure; it is
not a successful full check. A separately frozen missing-storage probe identifies
three additional Anvil receipt fallback calls, now forwarded read-only without
caching. The owned node still filters future source receipts: missing-storage
outputs remain unverified/not_mined without receipts, identical to uncached.

A deterministic watchdog initialization-gap test fails before the fix: an
inherited signal handler can consume SIGTERM before the watchdog initializes.
The fixed preparation kills its exact unreaped child with SIGKILL and reaps it;
the original early archive rejection and owned PID closure are preserved.
All27 focused checks pass after these fixes, including15 loopback cases, actual
complete original/omission/funding/oracle/provider controls and watchdog cleanup.
The second full suite runs312 tests/116.378s with one pre-existing cancellation
test synchronization error: its mock cancels on an empty selector poll before
the child writes its PID. A delayed-start regression reproduces that error;
the test now cancels on actual stdout readiness and checks empty polls plus the
unchanged owned-group cleanup. Production metadata code and10-second timeout
remain unchanged. Its targeted corrected check passes; both failed full logs
and the second run's explicitly after-launch source binding stay retained.
The third frozen full suite runs313 tests/146.341s with one pre-existing fake
worker startup race: a150ms timeout can precede its owned-state marker, so no
container exists to remove. A delayed-start regression reproduces the error.
The test now waits boundedly for actual creation before starting the unchanged
150ms timeout; a separate before-creation control proves no owner is removed
and the known client group closes. Both focused controls pass. All three failed
full logs remain distinct; production host timeouts and cleanup are unchanged.
The fourth frozen full suite runs314 tests/185.594s with an existing PID marker
read during its open/truncate/write window. Deliberately publishing an empty
marker reproduces the error; atomic sibling-file publication fixes it without
changing readiness bounds or owned-session assertions. Related worker markers
and fake owned-state fixtures now publish atomically;19 related controls pass.
One initial before-fix harness lacked its relative fixture and failed setup;
that raw record is retained separately from the corrected behavioral failure.
The25-source lint/type/security gate passes with all25 findings retained. A new
full native run and independent final review remain pending. Current
source coverage includes25 production files and25 retained security findings;
wheel coverage includes20 modules, and21 dynamic image inputs still need actual
image/default-worker CI. No archive replay, historical runtime improvement or
retrospective timeout-cause claim is made.

## 2026-10-02 — Safe RPC diagnostics, unpublished candidate

RPC exceptions now expose only fixed codes and allowlisted methods, while native
trace CLI failures retain the existing explanation with a safe classification
suffix. Provider error data/messages, URLs, parameters and partial HTTP body bytes
are excluded. An actual loopback response with valid JSON but a prematurely ended
Content-Length was accepted by the prior transport and is now refused. The
RuntimeError/RPCRejected relationships, method allowlists, response cap, default
worker error envelope and HTTP v0.1 contract remain unchanged.

Targeted author checks cover hostile exceptions/forged metadata, native CLI
propagation, actual loopback timeout/HTTP/rejection/malformed/truncated responses,
owned server closure and existing trace validation/mining deadline behavior. Full
source static/security checks retain all 23 reviewed findings without suppression.
Exact author logs and frozen sources are preserved privately pending independent
source review. This is not a full native/Docker suite or current-head CI result;
there is no new archive run or retrospective classification of retained failures.
Protected integration, publication and independent approval remain pending.

## 2026-10-01 — Whole worker preparation deadline, PR #22

The current bounded archive candidate now prepares the image in an owned POSIX
session. An independent watchdog caps all preparation phases at 600 seconds and
kills that session on expiry or owner-lifetime pipe EOF, including owner SIGKILL.
The operator can choose a shorter timeout. The parent cleans staging and publishes
the manifest atomically after successful preparation. Runtime/worker source,
container configuration, archive hashes and report contracts are unchanged.

The blocked-download regression failed before the fix. Final local checks pass
204 engine tests, including 15 build tests exercising a real stalled HTTP body,
native blocking call, SIGTERM, owner SIGKILL, an ignoring descendant, timer/handler
restoration and manifest failure preservation. Use the pinned Foundry 1.8.3;
an initial run with the unrelated Homebrew 1.6.0 correctly rejected recorded
observations. Ruff, mypy and the full source-bound 24-finding Bandit policy pass.

An actual BuildKit RUN sleeping for 60 seconds was stopped in 10.013 seconds by
a 10-second budget. A guest /proc query found no remaining probe process. A
normal build produced the same immutable image and complete fixture artifact
e6a12db320dd37e8d37341fe202836d9442a7e428f89381223c9ab29faa479a6.
Evidence and the Docker probe source are in evidence/worker-build-deadline/.

Independent approval, protected integration and cross-repository pin promotion
remain pending. Owner SIGKILL can leave staging/config files; cache/image/VM
storage, arbitrary caller quotas and uninterruptible kernel faults are not bounded
by this change. No new model/archive replay, upstream transaction, image
publication or paid service was used. See the coordination repository for the
broader release gates; this does not establish full goal completion.

## 2026-10-01 — Bounded default-worker Docker metadata candidate

The default worker previously buffered Docker `info` and `ps` without byte caps.
An actual valid info response over 1 MiB failed the new refusal regression before
this fix. Fixed metadata queries now read at most 4 KiB per chunk and reject
information above 1 MiB or admission/owner output above 128 bytes before parsing.
Each query retains a ten-second pipe/client deadline, nonzero exit failure and
ownership/controller validation. Finally kills only its new client process group,
including descendants retaining stdout; it never kills the daemon or removes a
foreign worker. Cleanup uses the existing owner-label/full-ID protocol.

All 212 local native/unit tests pass with Foundry 1.8.3. Six new real-pipe cases
cover exact boundaries, oversized valid JSON, flooding, a full ten-second timeout
with an exited leader/ignoring child, EOF-before-exit/status, and cancellation.
The initial cancellation probe interrupted Popen internals rather than the reader;
its corrected selector-bound probe and final full suite pass. All 22 production
sources pass Ruff/mypy and the full scanner retains 23 findings, with no suppressed
rules. Two metadata launch sites are consolidated; this reduction is not evidence
of fewer vulnerabilities. Updated exact source/finding rationales need independent
review.

Actual dedicated ARM64 Docker returns 11,576 info bytes and confirms all required
controllers. A new image changes only isolated.py among 18 inputs. The first full
22-case Docker run retained 19 passing resource/admission/lifetime/build tests but
three native/worker equality cases used the wrong host Foundry version. Only those
three were retried with 1.8.3; all pass without source/expectation changes, including
complete fixture/local-Anvil/risk/recorded-model equality. This is combined local
coverage, not a single all-passing full invocation. Current-head complete CI is
linked separately in the PR; evidence/docker-metadata/summary.json binds the logs.

This fix covers only default-worker info/ps captures. Other scanner/tool responses,
whole-host overhead, abrupt owner SIGKILL, process-launch/kernel stalls, Docker
cache/image/VM storage and archive egress limits remain. Frozen historical/model
inputs are unchanged and no new archive/model call, protected merge, deployment,
package publication or submission occurred. Coordination still selects the prior
review candidate until this focused stacked PR is independently reviewed.

## October 1 — Contract identity reproducibility review and fix

An independent Codex source reviewer reproduced a real Anvil v1.8.3 defect:
case-aliased local contract keys with STOP/revert code produced success/21,000 gas
versus revert/21,006 gas when only insertion order changed. Canonical scenario
bytes were identical. All four owned guardians exited and their RPC ports closed.
The original source, inputs, script and observations are retained in
`evidence/local-contract-identity/`, separately from the fix.

Validation now refuses duplicate normalized local contract addresses before any
node/Docker client for native, normal bounded and bounded-agent entrypoints.
One legitimate mixed-case override is preserved unchanged. Both-order refusal
regressions fail before the fix and pass afterward; all 214 native/unit tests pass
in 29.765s with pinned Foundry. Lint/format/type checks cover all 22 production
files. The full scanner retains all 23 findings and unchanged rationales; stale
source review fails before refreshing only the models.py source hash. Follow-up
independent code review confirms resolution; it is not a GitHub approval.

Actual current-head Linux native/Docker/image/native-provenance CI remains a
separate gate linked in this focused PR. No archive/model call, Docker/VM startup,
protected merge, deployment or submission occurred. Frozen report/holdout/source
inputs and v0.1 contracts are unchanged. Coordination still selects tested c167193
until a separately validated source promotion; main protection is retained.

## Same-block signed funding: native fix prepared, CI pending

The `fix/trace-funding-admission` candidate starts from tested engine8176597.
Only owned trace nodes defer parent-state pool balance/gas/fee admission to
actual ordered EVM/block execution. Two regressions fail before the fix; four
focused real-native regressions and248full native tests pass with0skips. Existing
RPC denial, fixed headers/signatures, guardian/memory/deadline and all v0.1
contracts remain. Full23-source lint/format/types and23retained Bandit findings
pass;42locked dependency identities have0reported advisories, fresh wheel built.
An ignored author runner's spawn-guard failure remains distinct from the fresh
required full pass. See [scope and raw evidence](evidence/trace-funding-admission/README.md).

This is disposable synthetic native funding proof, not a new historical replay,
model/holdout result or Docker-isolation measurement. A new no-network image
protocol case is pending CI; separate host default mainnet/image/native provenance
and cleanup gates remain unchanged. Existing SDKee/siteb7 offline inspection and
engine817 historical proof retain their exact prior sources. No Docker/VM startup,
upstream write, key retention, merge, deployment or submission occurred. Independent source/evidence review passed with no remaining actionable findings;
its exact pre-publication hashes are preserved. Exact-head CI and mandatory
human GitHub approval remain separate; overall goal active.

## Signed oracle dependency and provider-state coverage prepared

The `test/trace-oracle-provider-state` candidate starts from tested935558a/PR31.
Four actual native regressions cover signed CREATE parent setup, original
signed same-block oracle update20 plus an independent sender's consumer, adverse
omission from parent value10, and read-only local provider fault/control cases.
Both original receipts match gas26167/26438 and the consumer word20 log; omission
preserves its signature and reverts at25808gas with no logs. Source nonces/state
remain unchanged by replay. This is synthetic causal receipt proof, not profit,
historical price, oracle service or complete state truth.

Missing parent/code/balance explicitly fail; missing mining-time storage instead
can produce a sealed unverified `not_mined` baseline without receipts. The only
production change explains that receipt absence cannot identify the cause or
attest parent state. No state/signature repair, fallback or inferred error cause
was added. New direct image/protocol coverage awaits exact-headCI; default host
dispatch/lifecycle and historical gates remain separate unchanged checks.

After a preserved new-test import failure, four focused cases and252full native
tests pass with0skips/errors/failures. Full23-source lint/format/types and all23
retained scanner findings pass;42locked Python packages have0advisories. Nine
oracle/fault nodes and five proxy threads/ports close successfully. A diagnostic
generator's prior nine-node raw JSON/report overwrite is explicitly disclosed;
original aggregate investigation/root review and initial raw observations remain,
while the fresh current native proof uses a separate non-overwriting destination.
See [raw evidence and exact scope](evidence/trace-oracle-provider/README.md).

Independent source/privacy/evidence review passed with no remaining actionable
findings; three fresh reports also pass unchanged SDKee/siteb7 offline validators.
Original pre-publication hashes and evidence-loss disclosure remain preserved.
All eight exact-headCI checks are pending. No local Docker/VM, new archive/model/holdout/media operation,
upstream write, retained key, merge or deployment. Prior engine935/PR31 all-eight
CI and coordinator8029 evidence remain distinct; the overall goal remains active.

## Separate diagnostic same-invocation observation prepared

Published aac/PR32 has seven successful required checks and one failed isolated
check:25Docker tests and first-prefix default replay passed; the four-prefix
baseline matched originals, while candidate transaction2 was `not_mined`. A later
separate diagnostic completed; the original cause remains unknown. Later image
and native advisory gates did not run. No blind retry or weakened assertion.

The failure-only test helper now observes its own guardian invocation with a
fixed backend log filter, bounded finite event/index/EOF/truncation metadata and
exact worker envelope SHA/branch binding. All23production sources and normal
mandatory workflow commands remain unchanged. Owned reader/session cleanup and
primary replay error preservation have focused regressions. A frozen integrated
native synthetic control preserves full original receipts; missing storage emits
same-invocation execution-skip2/1 with an unverified baseline. All seven owned
nodes, eight readers and two proxy threads/ports close; source state is unchanged.
This is diagnostic observability, not the cause of the original historical fail,
a normal default-worker pass, profit or provider/state attestation.

See [frozen proof and precise test/evidence scope](evidence/trace-oracle-provider/same-run-observer/README.md).
Final independent source/privacy/evidence review passed; new-head required CI
and protected-main human approval remain separate. No local Docker/VM or new
archive/model/holdout/media operation. Current public composition remains
coordinator8029/engine935; unpublished integration awaits all component gates.
Overall goal active, with earlier raw-evidence loss disclosure retained.

## October 2 — Historical Aave read-only consumer price dependence

On unchanged engine198 production sources, native006 repeats original32 signed
inputs/block18999892/skip12 within the same150s trace cap. The baseline completes
with all32 full projected receipts equal to originals/prior successful baseline;
candidate executes31 and omits12. Later19 receipts change only index/cumulative
gas by the exact omission. New bounded owned-node reads show Aave's WETH source
equals the historical updated proxy, currency/unit and returned-code identities
stay fixed, and its price matches producer answers in all4 phases:257082415000
initially,256292441874 after baseline,257082415000 after omission. This shows
read-only consumer dependence despite unchanged remaining gas/status/logs, not
a signed consumer action, strategy benefit, profit or broader G1 completion.

Report132.703057s/native132.738311s/host132.865456s; one actual trial, no primary/
getter/snapshot/cleanup errors. Exact2Anvil+1cache closures and fresh root owned
PID/group/port probes pass. Aggregate cache7errors have unknown causes. Prior
001–005 immutable records are preserved; no speed/timeout-causality claim.

Root prelaunch review verifies100 fixed bindings/284prior records/25Git198
production files and corrected private stop delivery, finite deadlines and
unique4phase/24read bounds. Historical failures and the host-import setup gap
remain disclosed. Public portable33control sources and one mandatory quality
step make decoder/failure/cancellation controls reproducible offline; those
controlled tests are distinct from the actual native closure evidence. See
[raw evidence, source and reproduction scope](evidence/aave-consumer-price/README.md).
Public-layout verification, fresh exact-headCI and human main approval remain
separate gates. No candidate Pages, new model/video or submission claim.

## October 2 — Supported owned consumer observations (local candidate)

The separate native `trace-observe --native` CLI and
`consumer_observations.run_trace_observed_native` export version0.1.0 wrappers
containing the original trace report and four bounded fixed Aave/WETH view phases.
The actual Aave source is decoded on each owned node rather than assuming the
historical2024 proxy. Unsupported ABI/code/source/currency/unit remains unproven.
Price-read completeness and raw price difference are separate from historical
baseline receipt verification, signed consumer actions and economic benefit.

Local pinned Anvil1.8.3 controls cover signed synthetic oracle update20 versus
omission10 with an actual consumer revert, no-omission price difference0, missing
Aave code/unproven reads, native CLI export, SIGTERM before/after branch views and
sealing interruption after owned cleanup. Source-only synthetic genesis/code
adapters are explicit; there are no replay state/nonce/signature repairs or
archive calls. Six actual owned test methods pass, with recorded guardian/cache
group/port/pipe closure. Eighteen unit methods cover strict ABI/head/content
binding, bounds, finite hostile errors and cancellation through actual RPC
normalization. The24-method targeted run initially has one wrong expected error
count (six versus actual seven); its corrected single control passes separately.
Earlier19-method pass and the exact failed24 log remain retained privately.

Existing30 trace/protocol compatibility tests pass3.702s without skips. Full
26-source lint/format/mypy passes; the complete unsuppressed Bandit scan retains
all25 original exact findings/rationales and0 skipped rules. Only changed/new
source hashes are refreshed. The new module is packaged in a freshly built
wheel. Full native suite, independent source review, exact-head CI, historical
execution of this supported workflow and protected-main human approval remain
pending. Prior native006 research evidence is unchanged and does not constitute
execution of this new command. No Docker/model/browser/Pages/submission claim.

### Supported workflow final local checkpoint

The preceding targeted counts and initial wheel describe the earlier local
checkpoint. Two additional resealed controls now refuse mismatched initial-head
timestamps and mark future feed timestamps `feed_timestamp_unproven`; raw views
remain preserved. Round consistency and future-time sanity do not implement a
maximum-age freshness policy. The final new-method count is26:20 unit controls
and six real owned synthetic methods.

The first full native run007 failed:349 tests/205.173s, one failure and one error
in unchanged diagnostic cleanup controls. Its raw log is retained. An instrumented
repeat of only those two controls passes3.253s and does not identify the original
cause. One authorized plain full retry009, with identical production/tests/docs/
security digests, then passes all349 tests80.699s with0 skips. No runtime or test
fix, signal instrumentation, archive call or budget increase was applied for this
retry; no causal or speed claim follows from the different durations.

Current26-source lint/format/mypy and the full unsuppressed Bandit scan pass with
all25 exact prior findings/rationales retained. The new current wheel010 contains
all21 modules byte-identical to source; earlier wheel004 is retained as historical
pre-future-timestamp evidence. Actual synthetic results include signed source
transactions, adverse consumer reversion, finite unsupported views, cancellation
and owned Anvil/cache closure. Source-only fixture adapters are explicit.

Independent final source approval, public packaging/exact-head CI, execution of
this supported command against the historical32-input case, default-worker
wrapper support and protected-main human approval remain separate pending gates.
Normal trace/default-worker/HTTP envelopes remain unchanged. The150s signal guard
covers replay and owned cleanup; wrapper sealing/export happen afterward. No
whole-command sandbox, signed historical consumer action, profit, provider
state authentication or broader G1 completion is claimed.

The reviewed local checkpoint and retained failed/successful runs are now collected
in [owned consumer observation evidence](evidence/owned-consumer-observations/README.md).
Public-package review and exact-head CI are still pending; adding these copies
does not repeat the historical research trial or test suite.

### First public CI and failure-preserving test correction

Public candidate d300a24 passes quality and all four Python unit jobs; native,
isolated and documentation jobs fail. Native349/82.348s rejects a sender nonce
read in the missing-code control; a secondary expected-two-node assertion masks
that primary error and skips subsequent cache checks. The original rejection's
cause remains unknown. The test helper now checks all actually owned resources
before count checks and preserves unexpected primary errors. Intended-stop
cleanup failures still fail. Production/scripts/policy and original evidence
remain unchanged. Existing missing-code and a new actual primary-error regression
each pass once; the latter closes one replay node and one cache while preserving
the exact primary exception and keeping diagnostics free of private text/URLs.
Current27-method/whole350 verification is pending fresh mandatory CI.

Nine observed existing503 source links are repaired with matching versioned raw
files and three explicit source line ranges; all8unique targets pass the same
pinned checker with independent source review. Isolated CI's Docker metadata
verification failure remains unclassified; no controller or gate is relaxed.
See [focused logs, independent review and limits](evidence/owned-consumer-observations/followup/README.md).
Historical349 success is distinct from latest350 validation. Human main approval,
supported historical32 execution and deployment remain separate pending gates.


### October3 — Bounded admission and signed base remediation

Current native observation follow-up preserves four active cache handlers and
the shared trace deadline, adding at most100ms bounded admission for transient
slot overlap with explicit four-socket listen backlog. Actual HTTP before/after
controls and26 cache tests support the change; original Linux nonce rejection
cause remains unproven. The signed immutable Python base89281daa replaces the
old base with three pip-wheel findings; both remote platforms retain all26 old
OS names and scan31 packages/zero reported findings. Current built-worker/Linux
Anvil compatibility is still required by mandatory CI. No finding is ignored.

A full352 run failed one diagnostic cleanup assertion with unknown cause. Its
raw record is preserved. Finite secondary diagnostics and an actual overflowing
live-client control were added. Independent review found an assertion could skip
test rescue; try/finally plus false-success fault injection corrects it. Prefinal
353/82.985s passes; final354/79.788s passes with zero skips and all75 prelaunch
inputs unchanged. Eight owned replay cleanup records and three strict synthetic
wrappers are verified,21 wheel modules match current source. Production security
retains26 sources/all25 reviewed findings without suppression. No new archive or
model call, historical32 result, main merge, deployment or formal submission is
claimed. See [raw outcomes, provenance and reviews](evidence/owned-consumer-observations/remediation/README.md).
Fresh exact-head mandatory CI and protected-main independent human review remain
required; historical and current outcomes are distinct.


### Copied-base manifest binding

Public7b50 passes seven mandatory checks, including native354/83.227s with zero
skips and all four unit versions354/40 declared Anvil skips. Quality/source/wheel/
Python/research and20-doc/208-link artifacts are reviewed. Isolated25/218.049s and
default one/four replay pass, then the unchanged image guard correctly rejects
old011 metadata against new892 Dockerfile. The builder had a stale constant;
image/Cargo audits were not reached. New preparation derives the fixed flat
single-stage immutable base from copied Dockerfile before launch. Two metadata/
prelaunch controls use real copying/hashes with simulated Docker;20 build methods
pass before the independent continuation correction, and both base controls pass
after it. All eight malformed/floating/multiple/continued variants refuse before
launch. Final26-source scan retains all25 findings/reasons and original audit
guards. Current whole356/eight CI and real image audit remain pending; parent354
results are historical. See [cause, controls and final reviews](evidence/owned-consumer-observations/remediation/manifest-binding/README.md).

### October3 — Supported CLI reproduces the original32-input consumer case

Enginee9d629e supersedes the preceding pending356/image-audit checkpoint: all8
original mandatory CI runs pass and complete raw source/artifact reviews agree.
Native356/85.466s has zero skips; unit3.11–3.14 each356 has40 explicit Anvil skips;
actual isolated25/218.122s and default1/four replay pass. Current copied worker22
inputs/base892/source digest agree. Unsuppressed26-source/25retained findings,
21wheel modules,42Python/31OS/1126signedCargo identities have0 reported advisories;
21documents/222links pass. Database/tool binaries are not exported for independent
rehash;172nonCargo entries remain outside advisory coverage. Main still requires
strict/admin-enforced independent human approval.

The actual supported trace-observe native CLI now executes original32-of181
block18999892/skip12 once, exporting a strict sealed wrapper. All32 complete
baseline receipts and both full branch outcomes match original/native006 evidence.
Candidate executes31; later19 changes remain index-1/cumulativegas-336752 only.
All4 raw Aave consumer prices equal their producer answer: baseline257082415000
to256292441874, candidate unchanged257082415000, USD unit100000000. Both initial
heads/getters and stable nonempty oracle/source identities are verified. Replay
127.599511s/CLI127.803665s/host127.921839s retains original150s;31source/5input hashes
stay unchanged. Passive lifecycle profiling makes no production/RPC/state/limit
changes and does not support a speed claim. Owned2Anvil+one cache groups/ports/
pipes close, with independent host group/port probes. Cache1879/970upstream/903hits
retains6 aggregate errors of unknown cause and0refusals. Initial telemetry/host/
verifier preparation findings and five passing fault controls are preserved;
fixes precede the sole archive attempt. Initial overwritten readiness bytes are
explicitly unavailable; later raw readiness/reviews are retained.

See [usable offline wrapper, exact command, raw outcomes and scope](evidence/owned-consumer-observations/historical-32/README.md).
Read-only dependence is not a signed consumer strategy, profit, authenticated
provider/deployed code, full-block/root/opcode or default Docker32 result. New
documentation/evidence publication checks, protected-main review, deployment and
formal submission remain separate. No model call or upstream transaction broadcast was
added. Goal remains active through the official October13 15:59JST deadline;
Discord excluded.
# October 3 — default bounded fixed-price observations

Published4fdb664/PR35 with all31 remote Gitblobs verified and independent final
review297assertions/99inputs (SHAe99a429e840f2e5f53d3397724ad29bf1fdeb7d7f3f27c3c5ab619eb3af0dcac).
Its real isolated historical/security job37101478969 and quality/docs pass.
Original unit/EVM jobs fail at the new fake-client tests because a full wrapper
in one environment value exceeds Linux MAX_ARG_STRLEN; two actual bounded Linux
host probes reproduce errno7/both failures, then pass after owned response-file
transport. Full fixtures/controls and all production/image sources are retained.
Focused current protocol/metadata40 tests pass; no archive/model/Docker-suite
repeat is needed for this test-only repair. Corrected-head CI remains required.

The normal `trace-observe` CLI and `run_trace_observed` Python entry now use the
existing Docker worker. A closed fixed-profile JSON job retains256KiB input,
8MiB output, full request-hash/profile/nested-plan binding, shared admission and
exact owned cleanup. Native remains explicit; no HTTP endpoint or executable
extension is added. Observation150s and original worker180s deadlines compose
without resetting the outer lifetime. Independent review found and fixed clock
sampling order so scheduling cannot extend the inherited deadline. Native caller
alarm refusal and BaseException cancellation remain unchanged.

Actual default host Docker replay of32 original signed inputs at Ethereum
block18999892 passed:32 verified baseline receipts, one omitted candidate input,
complete four price phases and raw price difference789973126 in100000000 USD
units. Replay141.443232s/host142.447272s fit original limits; shared worker slot
is absent afterward. Full baseline/candidate outcomes, plan, raw ABI views and
classification equal historical native evidence. Both offline CLI readers using
SDKeb inspect the new wrapper. This is partial-block price dependence, not a
signed consumer strategy, profit or provider/full-block/root/opcode proof.

Native366/84.525s and actual Docker26/246.103s pass. The first current native366
attempt had an unchanged metadata cleanup PermissionError on macOS; focused and
full unchanged-source retry pass, with original failure retained and cause
unestablished. Initial Docker suite exposed three mismatched host Anvil1.6 vs
image1.8.3 comparisons and daemon-default unconfined seccomp. Host selection was
corrected to1.8.3 and every worker now explicitly requests seccomp=builtin;
actual kernel filtering passes without changing global settings or assertions.
One concurrent32 admission was refused before execution; only one executed
historical32 attempt is claimed.

Full26source/script Ruff/mypy/Bandit retain25 findings/0skips,42locked Python
identities/0reported advisories. Actual final local image840d03 has22exact source
inputs, unchanged base892 and pinned Anvil1.8.3. New required CI adds real default
observed historical one-input validation while preserving existing one/four
replays, security and lifecycle gates. New current-head CI, fresh image OS/Cargo
queries, final artifact-bound independent review, main approval, coordinator
promotion, live Pages and formal submission remain separate. Goal stays active
through the official deadline; no model/video/broadcast/paid/Discord work.
See [exact current evidence](evidence/bounded-consumer-observations/README.md).


## October 3 — Historical Aave account impact through the default worker

The separate trace-position format now compares a bounded existing account with
fixed Pool/provider/oracle/ABI queries on all four owned phases. Default Docker
request binds complete version/trace/account/profile; full result binds nested
price/trace seals, account and phase heads. Preserved v0.1 scenario/trace/price
formats, resources, original signatures, missing-state behavior and 150/180 caps.
Independent prelaunch found the account-unit relation unproven; two fixed returned
configuration getters now require matching historical provider/observed oracle
before any unit/difference claim. Unproven data has null differences; no-debt
uintmax health remains raw with no_debt status/null normalized difference.

One actual default13 replay passes: all13 original baseline receipts byte-match
priornative32 first13, candidate12exec/skip12, four fullprice/account/config/code
views error-free and initialaccount/head equal. Availableborrowbase difference
81628966124 (USD816.28966124), healthWAD3852169807877337; both aboveone. Trace
92.565119s/host95.486630s, exactimage2a0f2bc/source2af2329a23inputs, ownedslot absent.
Prelaunch harness wrongDockerfile-path failure retained; no actual restart.

Full27source Ruff/mypy/fullBandit25existingfindings0new pass;42tool locks/runtime
empty unchanged. Fullnative379/97.300s passes/0skips; later test-only quota variable
repair and additional closed hostbinding case pass final15/8.395s after host and checker-source binding, not a local
full381 claim. Previousfull374/103.769s has1 unchangedmacOS diagnosticcleanup
os_error, focused1pass and later379pass; cause remainsunknown. Legacy33controls
pass. Finalsame-image Docker26 passes with pinnedhostAnvil1.8.3 after initial
unpinnedhost26/3comparisonfailures; initialfailure retained, no image/resource
change. Finalwheel395276f9 binds22modules/all26RECORD/fullREADME and actual-I
installedread/CLIhelp; initial inheritedPYTHONPATH pip setup corrected. Docs24/293
allpass after badPoolfragment fix/noexclusions. Finalstage review, exacthead8CI/publication, coordinator
promotion/humanmain/Pages/submission remain separate. No signedloan/liquidation/
profit, soleWETHcausality or freshmodel/browser claimed. See
[evidence](evidence/aave-account-impact/README.md). Goalactive; Discordexcluded.

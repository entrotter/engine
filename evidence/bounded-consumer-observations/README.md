# Fixed Aave/WETH price observations through the default worker

The normal `trace-observe` command now uses the bounded Docker worker. The
closed job accepts only the installed Aave V3 Ethereum WETH profile and an
ordinary validated trace plan. It adds no callback, code, selector, URL or HTTP
endpoint. Native execution remains an explicit `--native` development option.

One actual host CLI execution replayed the first32 of181 original signed
transactions in Ethereum block18999892, omitting index12 in the candidate.
[The sealed result](observed-trace.json) has32 verified baseline receipts.
Complete baseline and candidate outcomes, all four raw ABI views, the plan and
classification equal the prior native record; see [comparison](comparison.json).
Both standalone terminal commands read this new result through SDKeb992 without
an engine runtime import: [inspection](cli-inspect.json), [verification](cli-verify.json).

Baseline Aave WETH price changes from257082415000 to256292441874; candidate stays
257082415000. The raw after-price difference789973126 uses USD unit100000000.
This is observed read-only price dependence, not a signed consumer strategy,
trade, return or profit. It does not prove a full block, roots, opcodes or provider
authenticity. [Earlier native evidence](../owned-consumer-observations/historical-32/README.md)
is historical evidence, separate from this Docker invocation.

The replay took141.443232s, and the host CLI142.447272s, on a configured running
Docker daemon and public archive provider. Both original150s trace and180s worker
limits stayed intact; no larger deadline, source-state repair, nonce repair or
fixture substitution was used. The shared worker slot was empty afterward.
See [observed runtime/cleanup](historical-result.json) and [exact image inputs](image.json).
These are measured invocation timings, not a speed comparison or availability
guarantee. Image build, VM startup and installation are outside this timing.

## Reproduce

Build/configure the worker from this checkout as described in the main README.
Use an operator-selected Ethereum archive provider and run:

```bash
export PYTHONPATH=src
export ENTROTTER_RPC_URL='https://YOUR_ARCHIVE_PROVIDER'
python3 -m entrotter_engine trace-observe evidence/aave-consumer-price/native-006/plan.json -o observed-trace.json
```

Provider latency and missing historical state can fail this bounded run. Missing
Docker, unsupported images and invalid/mismatched responses fail without a native
fallback or output replacement. JSON request hashes include the fixed profile;
both wrapper/nested hashes and the admitted nested plan are verified on the host.

The observer temporarily uses the earlier of its150s bound and the worker's
remaining lifetime, then restores only the original remaining time. Clock-first
sampling prevents scheduling delay from extending that deadline. Native caller
alarms remain refused; stop delivery remains a BaseException through owned cleanup.

Each container explicitly requests [Docker's built-in seccomp profile](https://docs.docker.com/reference/cli/docker/container/run)
alongside no-new-privileges and dropped capabilities. Actual kernel checks now
pass even when this daemon's default is unconfined; no global Docker settings
were changed. This is Docker's version-dependent profile, not a pinned Entrotter
system-call list or authorization to execute supplied code.

## Validation and retained limits

The first4fdb664 CI unit/EVM runs exposed a Linux-only fake-client transport
defect: the complete observed fixture exceeded Linux's per-string environment
limit. An actual bounded Linux probe reproduced errno7 and both failures, then
both passed after moving only fake response transport to an owned test file.
The full fixture and every request/plan/family assertion remain; production
worker transport already uses stdin and is unchanged. The same4fdb664 isolated
job passed all real worker/historical/security gates. Corrected unit/EVM CI is
separate from those retained first-attempt outcomes.

- [Native366 tests](native.log) and [actual Docker26 tests](docker.log) pass,
  including the real observed entrypoint, owned node cleanup, CPU/RSS/PID/tmpfs
  enforcement, admission races, cancellation and the actual180s idle deadline.
  The synthetic entrypoint test deliberately has no Aave adapter and retains
  four unproven views; it is separate from the real32 record above.
- [Full Bandit report](security.json) retains25 reviewed findings across26
  production sources/scripts with zero skipped tests. [Typing](types.log),
  [lint](lint.log), [format](format.log), [dependency coverage](dependency-manifest.log)
  and [42-package advisory query](dependencies.json) pass with zero reported
  Python advisories. This does not claim complete software security.
- One current native attempt encountered a macOS PermissionError during the
  unchanged metadata process-group cleanup test. The focused test and full
  unchanged-source retry passed. Its cause is not established; the failed log
  is retained privately and hashed in provenance, rather than labelled successful.
- The first Docker suite had three host/image Anvil-version comparison failures
  and one real missing seccomp filter. The host tool selection was corrected
  to pinned1.8.3 and the per-container profile was fixed; all assertions remain.
  The failed suite is retained privately. One32 admission attempt also correctly
  refused an occupied lifetime-test slot before execution; only one executed32
  attempt is claimed.
- Current-head CI, fresh image OS/Cargo advisory queries, independent main
  approval, coordinator promotion, live Pages and formal submission are separate.
  The local image is not a published registry image.

[Provenance](provenance.json) binds every exact public copy, current source hashes
and retained prior outcomes. Required CI adds a real default observed historical
one-input check while preserving all existing replay, security and lifecycle gates.

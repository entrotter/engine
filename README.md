# Entrotter Engine

[Workspace setup](https://github.com/entrotter/entrotter#quick-start-without-dependencies-or-an-api-key) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [MIT license](LICENSE)

MIT-licensed, Python 3.11+ local simulation software with no third-party Python package runtime
dependencies. This is an experimental local developer tool, not a secure public
multi-tenant service. See SECURITY.md before running it.

## Run from a checkout

The public runner, CLI and API now use the configured bounded Docker worker by
default, including synthetic fixtures. Follow the worker setup below first.
Docker absence or an invalid image fails execution; there is no native fallback.
Unit/native tests use explicit native execution and do not require a daemon.


```bash
export PYTHONPATH="$PWD/src"
python3 -m unittest discover -s tests -v
python3 -m entrotter_engine run tests/data/fixture.json -o report.json
python3 -m entrotter_engine serve --port 8787
```

`ENTROTTER_API_TOKEN` optionally enables bearer authentication for the local API.
The server always binds to 127.0.0.1, rejects browser Origin headers, validates
Host, bounds the request body to 256 KiB, admits at most eight connection handlers,
and permits one concurrent experiment.
It is built on the standard-library development HTTP server; do not use it as
an Internet-facing server, even behind a reverse proxy.

## API v0.1

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Local server health/version |
| POST | `/v1/runs` | Synchronous bounded experiment; stores a content-addressed JSON result |
| GET | `/v1/runs/{artifact_id}` | Reads a stored verified artifact |

Status codes: 201 created; 400 invalid scenario; 401 bad token; 403 disallowed
Host/Origin; 413 request too large; 415 wrong media type; 422 execution failed;
429 experiment busy; 503 connection/store busy; 507 artifact storage full.
Clients must not blindly retry a POST. There is no public job queue.

## Modules

`models.py` enforces scenario constraints. `fixture.py` implements two causal
policies over explicitly synthetic prices. `rpc.py` separates read-only upstream
calls from a write-capable local client. `evm.py` owns the Anvil processes and
runs baseline/candidate branches from identical starts. `artifact.py` seals
results. Public source RPC URLs are never embedded in artifacts.

The runner admits only JSON-defined, built-in actions. It does not execute
arbitrary Python, shell commands, downloaded agent code or LLM tool calls.

## EVM verification

Install Foundry/Anvil for the explicit native developer path and native tests:

```bash
PYTHONPATH=src python3 -m entrotter_engine run tests/data/local.json --native -o local.json
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The local case transfers native currency and calls a tiny reverting contract in
an isolated, artificially funded chain. Tests are skipped, not faked, without
Anvil. The dedicated GitHub workflow installs Foundry v1.8.3 and runs the same
suite. The adapter should not be considered EVM-validated until that check passes.

`evm-fork` additionally needs ENTROTTER_RPC_URL with historical state access.
The source chain ID and block number are checked and the resolved hash is
recorded. Supplying block_hash in the scenario additionally enforces a prior
pin. Local writes use chain ID 31337 and target only owned Anvil processes.
The supplied historical example is a template; it is not a published benchmark.

The Anvil command line may expose the archive URL to other processes of the
same OS user. Use only a trusted local machine and a restricted read-only RPC
credential. Archive providers may charge for reads; the user selects the provider.

## Limits and contribution priorities

There is no automatic replay of later blocks, mempool ordering, oracle event
stream, ERC-20 valuation, bridge state, MEV or independent security sandbox.
Do not interpret alternate transactions as the real future that would occur.
Contribute these capabilities with source provenance, fixtures, tests and
explicit assumptions. Do not add generic shell execution to the HTTP API.

## Token observations and Uniswap v3

The optional `tracked_tokens` v0.1 extension accepts at most eight allowlisted
`{address, symbol, decimals}` objects. Existing scenarios remain valid. Older
engine checkouts reject this extension; use the matching engine/scenario commits.
Decimals are verified with `eth_call`; malformed or failing token reads fail the
experiment. Reports include exact initial/final raw balances, per-slot deltas,
and gas cost derived from receipt gas usage and effective gas price. Token symbols
are user-supplied labels, not verified identities. Unlisted assets are excluded.

`entrotter_engine.defi` builds WETH deposits, exact ERC-20 approvals and Uniswap
v3 `ISwapRouter.exactInputSingle` calls with explicit deadlines and output floors.
It generates bounded JSON actions; it cannot broadcast. SwapRouter02 has a
different ABI and is not supported by this builder. Fee-on-transfer/rebasing
assets and price/portfolio valuation are not modeled. A zero output floor is
an explicit unsafe-policy comparison, not a recommended trading setting.

Anvil starts without default funded developer accounts, binds only to loopback,
disables persistent upstream storage caching and caps EVM memory to 64 MiB per
execution in native mode. Native mode is not a whole-process memory/CPU sandbox.
The default worker adds the kernel limits below. Arbitrary agent code stays disabled.

The minimal local token test fixture is deliberately deposit-only and cannot
return funds. It exists only on disposable test nodes. Rebuild its runtime with
Foundry v1.8.3: `cd tests/contracts && forge build`; solc 0.8.30 and the Cancun
EVM target are pinned in `foundry.toml`. The checked-in runtime allows offline
real-Anvil tests without downloading a compiler. ABI encoding is independently
compared with Foundry cast when available.

## Owned process lifetime

On POSIX systems, each Anvil process runs under a small standard-library guardian.
The owner holds a lifetime pipe; closing it or terminating the owner causes the
guardian to terminate and reap Anvil, including after owner SIGTERM or SIGKILL.
A separate watchdog expires after 150 seconds per node, followed by up to two
seconds of graceful termination before a forced kill. The normal branch deadline
and RPC timeouts still apply. Output is discarded, and the helper accepts no
commands over its lifetime pipe. Only the trusted executable/arguments constructed
by the engine are launched; it is not an arbitrary-agent code sandbox.

Tests send real OS signals to owners running real Anvil, kill the guardian itself,
and let the watchdog expire without owner cooperation. The owner's cleanup kills
the owned process group if the guardian fails. This improves lifecycle guarantees
but does not yet provide whole-run CPU/RSS/disk quotas. Simultaneously killing both
the owner and guardian is outside this native guardian's protection. EVM lifecycle
support currently requires POSIX; synthetic fixture execution remains portable.

## Default bounded local worker

A local Linux Docker daemon can enforce per-experiment resource limits. On macOS,
a separately configured Linux VM is required. Keep Docker accessible only to
trusted local operators. Build the image locally; the build script downloads a
SHA-256-verified Foundry v1.8.3 archive for the daemon's architecture and uses a
Python base image pinned by digest. It copies only engine source and Anvil into
the build context, records their hashes, and does not publish an image.

Archive staging is limited to 256 MiB, with at most 1 MiB read chunks and a
streaming SHA-256 check before extraction. `--archive` accepts regular files;
FIFOs and devices are rejected without waiting for a writer. The same byte bound
applies to downloads and files that grow while being copied. A 300-second transfer
budget is checked between reads; HTTP operations use a ten-second socket timeout.
This is not a hard whole-build deadline: connection/DNS, blocked filesystem I/O,
extraction and Docker builds are outside that transfer timer. Temporary staging is
cleaned on ordinary failure; SIGKILL can leave temporary files. Docker image/build
cache, total VM disk and caller-process quotas remain separate operator limits.

```bash
export PYTHONPATH="$PWD/src"
# Set this to your local daemon's absolute Unix socket if different.
export ENTROTTER_DOCKER_SOCKET=/var/run/docker.sock
python3 scripts/build_worker.py --output worker-image.json
export ENTROTTER_WORKER_IMAGE="$(python3 -c 'import json; print(json.load(open("worker-image.json"))["image_id"])')"
python3 -m entrotter_engine run tests/data/local.json -o report.json
python3 -m entrotter_engine serve --port 8787
python3 -m unittest discover -s tests_isolated -v
```

An unavailable daemon, invalid immutable image ID, exceeded budget or invalid
worker response fails the run; there is no native fallback. The host verifies
the complete report hash and exact input scenario before accepting the result.
Docker uses a temporary empty client configuration rather than stored registry
credentials. The dedicated Docker tests fail if the daemon/image is unavailable;
they are separate from offline and native-Anvil tests and require cgroup v2.
The owner-loss test can take approximately three minutes.

Each worker has one CPU quota, 512 MiB RAM, no swap, 128 process/thread slots,
a read-only root, a 64 MiB no-exec temporary filesystem and 16 MiB shared memory.
It runs as UID 65534 with all capabilities dropped and no new privileges. There
are no host bind mounts, exposed ports or persistent Docker logs. Input is
limited to 256 KiB and output to 8 MiB. A worker timer expires at 180 seconds;
the host stops waiting after 190 seconds and requests removal of its exact owned
container. Signal handling/Anvil cleanup can add a short termination grace. The
host checks that the container is absent; a daemon cleanup failure is explicit.
Daemon or VM failure is outside these application-level lifecycle guarantees.

Fixture/local-EVM workers have no external network. Historical forks enable the
Docker bridge for archive reads, with the operator's `ENTROTTER_RPC_URL` passed
as an environment variable. This is **not an archive-host egress allowlist**.
The URL can be inspected by trusted Docker administrators. Arbitrary user code,
agent imports and user-selected commands/images remain disabled. The image and
socket are operator configuration, never accepted from scenario JSON or HTTP.

These per-experiment quotas apply by default to `runner.run`, engine `run`, and
`serve`/`EngineServer`. `--isolated` remains an accepted explicit spelling.
All cooperating default runners, CLI invocations and API instances on the same
configured daemon share one worker slot. Docker atomically reserves the fixed
name `entrotter-active-worker`; an existing container, including a stopped one,
occupies the slot. Preflight rejection returns API 429 (`worker_busy_retry_later`);
the CLI fails without replacing its export. There is no queue or automatic retry. A
creation race may return the normal execution failure (API 422), because Docker
can reserve a name before its container is queryable. Failed starts are not
classified as safe-to-retry busy rejections; callers must not blindly retry a POST.

Cleanup checks the invocation's unique owner label and removes only its full
immutable container ID, never the shared name. A losing contender cannot delete
the winner. The independent 180-second timer bounds a started idle worker after
owner loss; the slot remains occupied until Docker removes it. A daemon failure
or a container abandoned before its entrypoint starts may require operator
inspection/removal of that exact ID. Failed admission/cleanup queries fail closed.
Do not clear the shared name merely because a client has exited.

This caps container worker concurrency per daemon, not Python caller processes,
Docker overhead, independent daemons, explicit native execution or older clients
using random worker names. Use matching host code and rebuild the worker image;
do not mix old and new runners on a shared daemon when relying on this bound.
Image/VM storage remains operator-controlled. CLI exports use the shared budget below.
The API connection/report bounds below apply in both modes. Remaining limits and independent security review are
open release gates; this does not make the engine a public multi-tenant service.


## Local API connection and report budgets

Both native and isolated servers admit at most eight connection handlers and one
experiment at a time. Extra connections receive 503 with `Retry-After: 1` without
creating a new handler. After sending 503, the server half-closes its output and
allows at most 100 milliseconds (including the send) to discard at most 320 KiB
of arriving request bytes. This bounded grace lets ordinary clients finish a POST
body without a TCP reset hiding the rejection. It neither admits an experiment
nor starts another thread. Slow/oversized senders can still observe a transport
error after the grace expires; overload is never a reason to retry POST blindly.
Each admitted connection has a ten-second inactivity
timeout and a 240-second absolute transport deadline. Trickle traffic cannot
extend that deadline. At expiry the socket is shut down; an already admitted
experiment completes or fails under its own execution budget before its handler
releases capacity. Closing the socket does not force-kill native Python work.
Each handler has at most one timer thread, joined before its slot is released.

`serve --output` is a dedicated trusted local report directory. The server limits
it to 128 MiB of file contents and 128 files, including unrelated files and
crash-leftover temporary files. A zero-byte `.store.lock` file is excluded. POSIX
file locks serialize cooperating writers even across separate local processes;
a busy lock returns 503. Temporary writes are included in capacity admission,
then atomically renamed. Reports are at most 8 MiB. A full store returns 507,
retains prior artifacts and never silently deletes reports. An identical saved
report can be returned again without consuming additional storage.

Export or remove unwanted files locally to reclaim space; there is no HTTP
endpoint that deletes reports. Startup rejects an already over-budget directory.
Stored report reads are bounded to 8 MiB and must match the requested content ID.
Symlinks, hard links, directories and special files are rejected. The directory
must be owned by the trusted operator; these are application quotas, not a host
filesystem quota against noncooperating programs or filesystem metadata. The
bounded API store requires POSIX; direct fixture execution remains portable.

CLI file exports also enforce 8 MiB per report and use exclusively created
private temporary files. A failed write preserves the prior destination. Exports to different user-selected directories share the export budget below.

## Quality and dependency checks

Production Python files in `src/` and `scripts/` are checked by Ruff lint/format,
mypy (including unannotated function bodies), and a full Bandit scan. Install the
pinned developer tools in a separate environment; runtime dependencies remain
empty. The complete tool/build graph is version- and SHA-256-locked.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements-quality.txt
.venv/bin/python -m pip check
.venv/bin/python -m ruff check src scripts
.venv/bin/python -m ruff format --check src scripts
.venv/bin/python -m mypy src scripts
.venv/bin/python scripts/check_security.py
.venv/bin/python scripts/check_dependency_manifest.py
.venv/bin/python -m pip_audit --strict --require-hashes --disable-pip -r requirements-quality.txt --progress-spinner off -f json -o .quality/dependencies.json
.venv/bin/python -m build --no-isolation --wheel --outdir .quality/wheels
```

The security scan uses every default Bandit rule with `--ignore-nosec` and keeps
all findings in `.quality/bandit.json`. `security-reviewed.json` records exact
finding fingerprints, per-finding rationales and hashes of every production
source/script. New, disappeared or changed findings, changed source, failed or
partial scans and scanner-version drift fail the review policy. The current 24
findings (20 low, four medium) concern trusted subprocess launches, a literal HTTPS
release download and an in-container tmpfs specification. Their author-written
rationales still require independent PR review; a matching policy is not an
independent security audit or evidence that the software has no vulnerabilities.

The dependency-manifest gate requires every declared runtime, optional-runtime
and build requirement to be exactly pinned in the audited lock. `pip-audit`
queries current Python advisories for the complete locked graph, fails collection
errors and uses no ignored-vulnerability list. Native Anvil, the Python runtime,
container OS packages and the Docker daemon are outside that Python scan's scope.
Mypy checks normal typing rules; JSON boundaries still use runtime schema checks
and are not claimed to be fully statically typed. Tests run separately, including
actual native Anvil and Docker enforcement; offline checks cannot replace them.

To update tools, edit `requirements-quality.in`, regenerate the complete hashed
lock with the pinned `pip-compile`, and rerun the entire quality workflow. Do not
hand-remove findings or suppress scanner rules to turn CI green. Review changed
source and the full scan before refreshing finding/source fingerprints, then
request independent review. The job uploads scan/audit reports and the built wheel.
GitHub Actions in this repository use immutable commit IDs.

## Migrating from the native default

The JSON v0.1 contract and deterministic artifacts are unchanged. Execution
prerequisites change: build a worker image from this checkout and configure its
immutable ID and local Docker Unix socket before running normal commands. Rebuild
when source changes; an old image is not evidence for the new source. The host
requires Docker/cgroup v2, while Anvil is supplied inside the image.

For trusted development, deliberately opt out with `run --native` or `serve
--native`. Python callers can explicitly use `runner.run_native(scenario)` or
`EngineServer(..., isolated=False)`. These paths retain native lifetime cleanup,
input/report bounds and API connection/storage limits, but have no whole-process
CPU/RSS sandbox. A container uses run_native internally because Docker already
enforces its limits; it does not try to start nested Docker.

```bash
# Trusted offline native example, explicitly outside the worker resource sandbox:
PYTHONPATH=src python3 -m entrotter_engine run tests/data/fixture.json --native -o report.json
```

Neither HTTP request JSON nor scenario data can select native execution. Local
scenario files must be regular files and reads stop after 256 KiB plus one byte;
FIFOs/devices cannot block waiting for input. This does not impose host filesystem
quotas or prevent a noncooperating local administrator changing files/processes.

The native test suite explicitly selects the native primitive to retain its
original coverage. Separate real-Docker tests exercise default public runner,
CLI and API entrypoints, complete artifact equality and actual kernel limits.
No daemon is required for the regression tests proving all defaults reject an
unavailable worker without writing or replacing reports.

## Worker image supply chain and advisory gate

The worker uses a digest-pinned public Chainguard Python 3.14 image with its
runtime libraries. It has no installed shell, package-manager commands or importable pip module. The
upstream pip bootstrap wheel is inventoried as an OS package. Anvil remains the
same checksum-verified Foundry 1.8.3 binary; build manifests also record its SHA-256.
The host supports Python 3.11 through 3.14; native and container runtimes are
separately tested. No registry account or paid image tag is used.

After building, run the advisory gate from the checkout:

```bash
PYTHONPATH=src python3 scripts/check_image_security.py --manifest worker-image.json --output .quality/image-security
```

This downloads checksum-pinned Trivy 0.74.0 and Cosign 3.1.3 binaries, verifies the
base image's exact digest and official signing identity, and scans the actual
locally built image ID. It uses empty private configuration/ignore files and does
not inherit scanner environment overrides or registry credentials. The complete
OS/language package inventory, all vulnerability severities, base signatures,
scanner/database hashes and database timestamps are retained. A database older
than one day, expired update window, unexpected image/source/interpreter/libc/TLS
inventory, scanner failure or any finding fails the gate. Unfixed/low/unknown
findings are not ignored. The real-Docker CI uploads reports even on failure.

The scan covers detected packages, including the packaged Python interpreter and
shared libraries. It does not establish native Anvil dependency coverage when no
Rust inventory is detected, audit the Docker/VM/host kernel, or prove the absence
of vulnerabilities. Native dependency coverage and independent review remain
release gates. Base-image/provider availability and public advisory data can
change; update the immutable digest deliberately and rerun signature, package,
real worker and complete-report equivalence checks. Never weaken filters or
suppress findings to restore a passing job.

Upstream references: [image provenance](https://images.chainguard.dev/directory/image/python/provenance),
[Trivy Rust inventory coverage](https://github.com/aquasecurity/trivy/blob/v0.74.0/docs/guide/coverage/language/rust.md).


## Native Foundry release inventory

The separate native gate verifies the upstream Foundry 1.8.3 SLSA provenance and
archive-bound signed SPDX inventory. It requires the exact release workflow,
OIDC issuer and source commit, archive checksum, and the builder's extracted
Anvil checksum. The downloaded SBOM must equal the cryptographically verified
predicate. Cosign and Trivy use the same checksum pins as the image gate.

```bash
PYTHONPATH=src python3 scripts/check_native_security.py --manifest worker-image.json --output .quality/native-security
```

Every Cargo name/version/package URL in the signed inventory must appear exactly
in the scanner result. A current, unexpired advisory database and all severities
are required; every reported finding fails. Raw signatures, inventories, findings
and hashes are uploaded by the actual-worker CI. Optional `GH_TOKEN` authenticates
only the upstream public attestation API, preventing anonymous rate limits; it is
not passed to Cosign/Trivy or recorded in reports.

The upstream workflow scans the entire Foundry checkout. This verifies advisory
coverage of its 1,126 inventoried Cargo packages, not the precise feature/target
subset linked into Anvil. The 172 entries without Cargo URLs, including local
workspace code and Actions, are listed explicitly outside this scan. Compiler,
C libraries, missing/uninventoried dependencies and upstream build compromise
remain limitations. Provenance proves origin/claims, not independent code review
or bit-for-bit reproducible compilation. The separate image gate covers detected
OS/interpreter packages; broader security/release gates remain open.

[Upstream pinned release workflow](https://github.com/foundry-rs/foundry/blob/cae51ad458f6abb64852b7709eb784352429825d/.github/workflows/release.yml).

## Shared report export budget

Standalone and engine CLI exports share a private POSIX bookkeeping directory:
`~/.local/state/entrotter/export-budget-v1`. Operators may set
`ENTROTTER_EXPORT_STATE_DIR` to one other private directory; all cooperating
clients must use that same directory. Requested `--output` paths keep their
existing meaning. No engine/SDK runtime dependency is added by this mechanism.

The budget is 128 MiB of tracked file contents and 128 files across output paths,
including reserved/incomplete writes. Each report remains at most 8 MiB. Admission
uses a nonblocking process lock. A durable reservation precedes creation of output
bytes, and replacement reserves the old file plus the new temporary file. A full
or busy budget rejects the write without replacing its prior destination. An
identical complete tracked export is idempotent, including at capacity.

```bash
python3 -m entrotter_engine exports
```

The command shows charged paths, pending temporary files and current usage.
Remove unwanted reports or listed abandoned temporary files locally; subsequent
admission reconciles missing files. Completed reports are never auto-deleted.
Do not delete/reset the ledger to free space: that discards tracking of existing
outputs. Invalid, inaccessible or insecure bookkeeping fails closed.

A process killed before rename can leave a temporary file, whose full reserved
size remains charged. After rename, the reservation recognizes only an exact
size/SHA-256 match at the final path. Ambiguous state retains its charge. Ordinary
exceptions remove only the owned temporary inode. Ledger contents are limited
to 256 KiB, with at most one additional 256-KiB staging file and an empty lock.

These are application file-content bounds for matching writers using one state
root. They do not constrain pre-existing untracked files, operator moves/renames,
noncooperating programs, older clients, separate state roots, filesystem metadata,
image/VM storage or all host processes. State is private to the local operator;
paths/report contents are not uploaded. POSIX locking is required even for API-only
CLI exports. The engine API's dedicated report store retains its separate quota.
A run can complete before an export is refused; do not blindly retry an API POST.

The stdlib-only `export_budget.py` is deliberately vendored identically in the
independent engine and CLI packages. Cross-repository CI requires byte equality
and verifies shared admission using both real CLIs and separate mixed processes.
Any protocol change must preserve this shared-state contract or use a deliberately
migrated protocol version; never silently reset existing reservations.

## Bounded causal agent decisions and recorded replay

`runner.run_agent` runs the built-in current-state risk policy, or replays a JSON
recording, inside the same default worker. Build the image from this checkout
before use. It shares the daemon admission slot, quotas, lifecycle and cleanup
with ordinary runs; Docker failures never fall back to native execution.

```python
import json
from pathlib import Path
from entrotter_engine.runner import run_agent

scenario = json.loads(Path("tests/data/local.json").read_text())
report = run_agent(scenario, decision_steps=[0, 1])
replayed = run_agent(scenario, decision_steps=[0, 1], recording=report["agent"])
assert replayed == report

# Reproduce the already recorded model decisions without calling a model:
recorded = json.loads(Path("tests/data/agent-recorded-local.json").read_text())
assert run_agent(recorded["scenario"], decision_steps=[0, 1],
                 recording=recorded["agent"]) == recorded
```

The policy sees the current proposal, current node state, completed actions and
current-state `eth_call`; it cannot see future steps, scenario labels or future
prices. It chooses only `hold` or execution of the unchanged allowlisted proposal.
Responses bind to the observation hash. Selection is limited to 1–32 unique steps;
the cumulative requested-gas budget defaults to 2,000,000 (21,000–64,000,000 allowed).
Shared setup is outside that budget. Preflight uses the current block while the
actual action mines 12 seconds later, so a successful preflight is not a promise
of successful execution. No valuation, market response, MEV or later-block replay
is introduced. Recorded replay requires identical observations and consumes all
selected decisions; changing initial state or the budget fails explicitly.

Scenario and public v0.1 result/agent JSON contracts are unchanged. The internal
agent worker envelope has its own version (`1`) and binds the response to the
entire request digest, including selection, gas budget and recording. Scenarios
remain at most 256 KiB; agent observations are 64 KiB, responses 4 KiB, recordings
3 MiB, and the complete agent envelope is at most 4 MiB. The worker bounded read
therefore admits 4 MiB before dispatch; ordinary raw scenario requests still fail
above 256 KiB. Complete worker output, including the envelope, remains capped at
8 MiB. These are transport/storage limits, not a memory sandbox for host Python
callers serializing objects. No agent endpoint is added to HTTP or the CLI.

This integrates the **unmerged experimental** causal-agent prototype
`bb8b3e8d32c7cbd49629d337758f30bfdf805045` with the hardened worker. Its previous
`run_agent(scenario, controller)` Python call becomes explicitly
`run_agent_native(scenario, controller)` for trusted custom providers. The new
bounded entrypoint accepts keyword-only decision data and never a Python provider
object, module, command, model name, URL or image. This is an experimental Python
API migration, not a change to a published package or the v0.1 wire schema. Existing
frozen benchmark checkouts and scripts remain pinned to their original version.

`AgentController` / `RiskPolicy` / `ReplayPolicy` remain available for the explicit
native developer API. Controllers are single-use, including after failure.
Custom `decide` calls execute trusted caller code in the host process; they have
no whole-process CPU/RSS/egress bound. Providers must implement their own bounded
transport. Do not use this path for untrusted code or a hosted service. Generation
can be nondeterministic; replay is exact only for matching observations. Recorded
provider metadata is provenance data, never an instruction to load a provider.

The native suite and dedicated Docker suite both replay the checked-in original
model report exactly. The Docker suite additionally exercises a recording larger
than 256 KiB, gas-budget refusal, state divergence, cleanup/recovery and equality
with native risk decisions. Offline protocol faults do not replace those real
executions. All integrated production modules receive the same unsuppressed
lint/type/security checks; independent PR review remains required.

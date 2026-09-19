# Entrotter Engine

[Workspace setup](https://github.com/entrotter/entrotter#quick-start-without-dependencies-or-an-api-key) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [MIT license](LICENSE)

MIT-licensed, Python 3.11+ local simulation software with no third-party runtime
dependencies. This is an experimental local developer tool, not a secure public
multi-tenant service. See SECURITY.md before running it.

## Run from a checkout

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

Install Foundry/Anvil before:

```bash
PYTHONPATH=src python3 -m entrotter_engine run tests/data/local.json -o local.json
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
execution. This is not a whole-process memory/CPU sandbox; those quotas remain
open. Arbitrary agent code stays disabled.

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

## Opt-in isolated local worker

A local Linux Docker daemon can enforce per-experiment resource limits. On macOS,
a separately configured Linux VM is required. Keep Docker accessible only to
trusted local operators. Build the image locally; the build script downloads a
SHA-256-verified Foundry v1.8.3 archive for the daemon's architecture and uses a
Python base image pinned by digest. It copies only engine source and Anvil into
the build context, records their hashes, and does not publish an image.

```bash
export PYTHONPATH="$PWD/src"
# Set this to your local daemon's absolute Unix socket if different.
export ENTROTTER_DOCKER_SOCKET=/var/run/docker.sock
python3 scripts/build_worker.py --output worker-image.json
export ENTROTTER_WORKER_IMAGE="$(python3 -c 'import json; print(json.load(open("worker-image.json"))["image_id"])')"
python3 -m entrotter_engine run tests/data/local.json --isolated -o report.json
python3 -m entrotter_engine serve --isolated --port 8787
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

Native execution remains the default, and these quotas apply only with
`--isolated`. Image/VM storage and total work launched by independent CLI
invocations do not yet have aggregate quotas. The API connection/report bounds
below apply in both modes. Remaining limits and independent security review are
open release gates; this does not make the engine a public multi-tenant service.


## Local API connection and report budgets

Both native and isolated servers admit at most eight connection handlers and one
experiment at a time. Extra connections receive 503 with `Retry-After: 1` without
creating a new handler. Each admitted connection has a ten-second inactivity
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
private temporary files. A failed write preserves the prior destination. Exports
to different user-selected directories have no shared aggregate quota; their
retention and free disk space remain the operator's responsibility.

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
partial scans and scanner-version drift fail the review policy. The current 15
findings (13 low, two medium) concern trusted subprocess launches, a literal HTTPS
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

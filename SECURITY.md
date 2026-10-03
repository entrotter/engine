# Security

The separate `trace-position` format admits one bounded account address and an
unchanged trace plan, and only the built-in fixed Aave Ethereum pool getter.
Two fixed getters bind Pool→addresses-provider→the observed price oracle before
account base-unit claims. Its exact worker envelope and complete result bind the requested account and
trace, every phase head and nested price/trace hashes. It cannot select supplied
callbacks, arbitrary selectors, contracts or transaction actions. Read-only
account observations share existing owned-node cleanup, 150/180-second limits,
64 KiB observation/8 MiB result bounds and atomic export quota. An account call
has a fixed ten-second cap within the same deadline; it never retries.
Missing/incomplete/state-mismatched views have null differences. Content hashes
are integrity checks, not authentication of pool implementations or providers.

Experimental research software. Do not use production keys, custody real
funds, or expose the local engine port or Anvil JSON-RPC to the Internet.
This is not a trading execution service. Mainnet broadcast is not supported.

Worker setup stages at most 256 MiB of a Foundry archive and verifies its pinned
digest in bounded chunks before extraction. Local archive inputs must be regular
files. POSIX preparation has a separate 600-second lifetime watchdog. Build
diagnostics are streamed in at most 64 KiB chunks and forwarded at most 1 MiB plus
one explicit truncation notice; excess is discarded without accumulation. A total
temporary-directory quota after SIGKILL, Docker daemon/BuildKit storage and other
Docker JSON-response captures remain outside these bounds. Image/VM disk limits
are separate operator controls. Preparation reaps its exact owned watchdog PID
with SIGKILL even when inherited signal handling has not initialized; it does
not wait for a consumed SIGTERM to run down the whole build deadline.

The engine runs only built-in policies. A Python import or a subprocess is
not a security sandbox for untrusted agent code. Container/process sandboxing,
egress controls, authenticated multi-tenancy and a production job queue remain
release gates before any hosted service is made available.

Every worker explicitly requests Docker's built-in seccomp profile as well as
no-new-privileges and dropped capabilities. A daemon configured with an
unconfined default cannot silently remove this filter. Unsupported profile
setup fails execution; there is no unconfined/native retry. This built-in
profile depends on the operator's Docker version, not an Entrotter-pinned list
of permitted system calls. It does not authorize external executable code.

Signed transaction-prefix replay accepts only bounded data plans, with no keys,
URLs, imports or commands in JSON. Upstream RPC cannot broadcast. A separate
owned loopback Anvil profile permits raw signed inputs and fixed header setters,
but denies balance/code overrides, impersonation and unsigned transactions.
Normal RPC still denies raw submission. Default trace execution uses the same
bounded Docker worker and shared admission/cleanup controls; its archive bridge
is not an egress firewall. Native trace execution requires explicit opt-out.
Receipt matches cover only the projected prefix fields, not block/state roots,
provider authenticity or economic outcomes. Trace-only deferred pool admission
allows earlier same-block funding while retaining EVM validity checks. Missing
parent/account state can fail explicitly; mining-time archive/storage failures
can leave an unverified `not_mined` baseline. Receipt absence does not identify
the cause or attest parent state; no fixture state or oracle response is supplied.
Trace checksums and
worker request binding establish integrity, not independently recomputed receipt
equivalence. See README.md and the raw evidence for limits.

The separate `trace-observe` command runs only a fixed owned-node
Aave/WETH view profile through the default bounded worker. Its exact private
worker envelope admits only the fixed profile and validated trace plan, with
complete request-hash and nested-plan binding; ordinary trace results cannot
substitute for observed wrappers. No HTTP endpoint is added. It never admits
callbacks, caller-selected addresses/selectors or code. A strictly decoded
on-chain source address selects bounded read-only code/ABI calls on the owned
node. Unsupported sources remain unproven. Four phases/36 queries share the
150-second trace deadline with at most two seconds per read; accepted code and
observation records are each capped at 64 KiB (transport remains 4 MiB). The
8 MiB wrapper uses existing export accounting. Main-thread POSIX cancellation
uses a non-Exception stop that cannot become an ordinary RPC timeout; it reaches
owned cleanup. The container entrypoint alone hands its active one-shot lifetime
alarm to this guard: the earlier of 150 seconds or its remaining lifetime applies,
then only the original remaining lifetime is restored. Expired deadlines stop
execution instead of disabling the outer bound. Explicit `--native` still refuses
existing caller alarms and restores prior handlers. Sealing/export occur after
owned resources close and outside the observation execution guard; worker sealing
and output remain under its original 180-second lifetime. Native whole-process CPU/RSS quotas, provider/deployed-code authenticity
and signed consumer actions are not established by view/hash checks.

The trace-only parent read bridge runs fixed installed code in an owned child,
never code or a URL selected by a plan. Private configuration crosses a bounded
stdin pipe; only a finite startup record and counters appear on stdout, and
stderr is discarded. The same pipe binds the child lifetime to its owner. It
listens only on loopback with an unpredictable per-run path, rejects browser
Origin and transfer-encoded requests, bounds handlers/requests/response/cache
bytes and shares the original trace deadline. No redirects, proxy-environment
settings or upstream writes are allowed. Successful exact-parent-hash read
results and hash-checked parent headers are reused; provider failures and other
blocks are not cached. This is an optimization of declared provider responses,
with at most four eligible in-flight keys and no additional handler threads.
Only cached successes are shared; failed owners release waiters on every exit.
Distinct keys and uncached receipt/volatile reads perform I/O independently;
short cache/counter locks do not extend the shared deadline. This is
not provider/state authentication or an egress firewall. Child process-group
kill/reap closes blocked upstream handlers on cancellation; normal worker
CPU/RSS/PID controls remain the only whole-process quotas. No host disk cache or
HOME mutation is used.

Do not post secrets or exploit details in public issues. Use GitHub private
vulnerability reporting where enabled. If it is not yet enabled, ask the
maintainers in an issue to enable a private channel without disclosing details.
RPC URLs can contain secrets: never include them in reports, commands in
screenshots, logs, pull requests, or issue bodies. The optional fork URL may
be visible to other processes owned by your OS user; run on a trusted machine.

RPC exception diagnostics contain only locally validated finite codes and fixed
allowlisted methods. Native trace errors can display these safe fields; worker
and HTTP error envelopes remain fixed. Provider messages/codes, partial HTTP
bodies, URLs and request parameters must not be included. Transport errors are
classified by exception types rather than error text; the normalized transport exception is raised outside
the original private exception handler. A code describes an observed
transport failure, not a diagnosis of provider state or miner internals.

The default worker checks bound Docker `info` to 1 MiB and its `ps` admission/
ownership response to 128 bytes before parsing. Both use bounded chunk reads,
a ten-second pipe/client deadline and owned-process-group cleanup on timeout,
reader failure or Python cancellation. Arbitrary native callers, sudden owner
SIGKILL, process launch/kernel stalls and other Docker/tool response captures
remain outside this metadata helper's guarantees. Docker itself stays trusted;
a bounded response is not proof of honest daemon state.

The default isolated worker adds tested per-experiment Linux kernel quotas,
non-root/read-only execution and no network for non-fork modes. Fork workers
still use a general bridge network; arbitrary code execution stays disabled.
Native execution requires an explicit trusted-development opt-out (`--native`
or `run_native`); it is not a whole-process CPU/RSS sandbox. The local API bounds
connection handlers and dedicated report storage; individual CLI exports are
size-limited. Default worker concurrency is capped to one container per daemon.
Explicit native/older clients and separate daemons do not share this bound; host
process overhead, CLI export retention and image/VM storage are not capped. See
README.md for the exact boundaries and operator-trusted Docker image/socket
requirements. Docker administrator access
can reveal the archive URL; never use a production signing key in this tool.

The quality workflow publishes the full Bandit report, including 25 explicitly
reviewed expected findings, and audits the hash-locked Python tool/build graph.
It does not suppress Bandit rules or advisory IDs. Exact source/finding changes
invalidate the review manifest. These author-provided rationales require human
review and do not establish security of native binaries, OS packages, container
isolation or arbitrary external code. See README.md for scope and reproduction.

The worker image additionally has a strict package advisory gate and verified
base signature. Every detected vulnerability fails, including unfixed and low
severity findings; raw reports remain visible. Coverage requires the packaged
interpreter/libc/TLS inventory and a current vulnerability database. Anvil's
native dependency graph, the Docker daemon and host kernel/VM are not proven
covered by a zero-finding image package scan. See README.md for exact boundaries.


The native release gate verifies archive/Anvil provenance and scans every Cargo
package in the upstream signed checkout SBOM. It records non-Cargo entries
outside coverage. This is broader than the binary's actual linked dependency
subset and does not establish complete compiler/C-library/build-system coverage
or reproducible compilation. Keep the inventory and scope visible; never suppress
an advisory or claim that a signed provenance statement proves software security.

CLI export accounting assumes cooperating versions sharing one private operator
state directory. Pending reservations survive abrupt process death and remain
charged. Never reset the ledger while retaining its outputs. Operator file moves,
other applications, old clients and distinct state roots are outside this budget;
this is not a whole-filesystem quota. Inspect usage with the exports command.

The bounded agent API accepts only built-in risk decisions or data-only recorded
replay. The private worker protocol has an exact envelope shape/version, validates
selection/budgets before node launch, and binds its response to the complete input
hash. Recordings cannot select code, imports, commands or network destinations.
The local-EVM worker has no external network; fork workers retain the general
archive bridge limitation above. Response hashes detect corruption and mismatched
requests, not a malicious operator-selected image.

`run_agent_native` deliberately executes a trusted caller-supplied provider object
outside the container. It is never a fallback or selectable from HTTP/scenario
JSON. Before/after decision deadline checks cannot interrupt a hung arbitrary
Python callback. Never describe native provider calls as sandboxed. Provider
metadata/recordings must contain no secrets before saving or sharing a report.

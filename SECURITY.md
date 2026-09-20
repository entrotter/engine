# Security

Experimental research software. Do not use production keys, custody real
funds, or expose the local engine port or Anvil JSON-RPC to the Internet.
This is not a trading execution service. Mainnet broadcast is not supported.

Worker setup stages at most 256 MiB of a Foundry archive and verifies its pinned
digest in bounded chunks before extraction. Local archive inputs must be regular
files. Transfer time checks and socket timeouts do not provide a hard whole-build
deadline, a total temporary-directory quota after SIGKILL, or image/VM disk limits.

The engine runs only built-in policies. A Python import or a subprocess is
not a security sandbox for untrusted agent code. Container/process sandboxing,
egress controls, authenticated multi-tenancy and a production job queue remain
release gates before any hosted service is made available.

Do not post secrets or exploit details in public issues. Use GitHub private
vulnerability reporting where enabled. If it is not yet enabled, ask the
maintainers in an issue to enable a private channel without disclosing details.
RPC URLs can contain secrets: never include them in reports, commands in
screenshots, logs, pull requests, or issue bodies. The optional fork URL may
be visible to other processes owned by your OS user; run on a trusted machine.

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

The quality workflow publishes the full Bandit report, including 24 explicitly
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

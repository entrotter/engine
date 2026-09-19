# Security

Experimental research software. Do not use production keys, custody real
funds, or expose the local engine port or Anvil JSON-RPC to the Internet.
This is not a trading execution service. Mainnet broadcast is not supported.

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

The quality workflow publishes the full Bandit report, including 15 explicitly
reviewed expected findings, and audits the hash-locked Python tool/build graph.
It does not suppress Bandit rules or advisory IDs. Exact source/finding changes
invalidate the review manifest. These author-provided rationales require human
review and do not establish security of native binaries, OS packages, container
isolation or arbitrary external code. See README.md for scope and reproduction.

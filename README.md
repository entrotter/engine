# Entrotter Engine

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
Host, bounds the request body to 256 KiB, and permits one concurrent experiment.
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
429 busy. Clients must not blindly retry a POST. There is no public job queue.

## Modules

`models.py` enforces scenario constraints. `fixture.py` implements two causal
policies over explicitly synthetic prices. `rpc.py` separates read-only upstream
calls from a write-capable local client. `evm.py` owns the Anvil processes and
runs baseline/candidate branches from identical starts. `artifact.py` seals
results. Public source RPC URLs are never embedded in artifacts.

The wire API admits only JSON-defined, built-in actions. It does not execute
arbitrary Python, shell commands or downloaded agent code. The optional local
Python controller below can accept typed decisions from a trusted provider.

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

## Causal decisions and exact replay (experimental local Python API)

```python
from entrotter_engine.agent import AgentController, RiskPolicy, ReplayPolicy
from entrotter_engine.runner import load, run_agent

scenario = load("tests/data/local.json")
report = run_agent(scenario, AgentController(RiskPolicy(), [0, 1]))
replayed = run_agent(scenario, AgentController(ReplayPolicy(report["agent"]), [0, 1]))
assert report == replayed
```

Only selected candidate slots are decisions; other slots are shared operator
setup. The provider receives current balances, completed-action summaries, the
current validated proposal, a current-state `eth_call`, and a requested-gas budget.
It returns exactly `request_id`, `choice` (`execute` or `hold`), and a bounded
`reason`. It cannot change the target, calldata, value or gas. Requests exclude
the scenario title, provenance and future slots. The operator must also keep
proposal construction causal; this interface cannot detect hindsight embedded in
operator inputs or a model's training data.

`RiskPolicy` executes only if preflight succeeds and the proposal fits its gas
budget. Preflight is at the current block; mining advances 12 seconds. Time-sensitive
contracts can therefore behave differently at execution. This policy prevents
some obvious failures, not all failures, losses or malicious approvals. No future
prices or portfolio valuation are available, so there is no defensible drawdown
or profit metric for this EVM example.

`agent` is an optional result extension with its own `agent_version: 0.1.0`,
provider metadata and ordered request/response exchanges. The scenario contract
and existing non-agent results are unchanged. The content hash covers the record;
it is tamper detection, not provider authentication. Replay requires exact
observations, rejects missing/extra decisions, and uses no model call. A changed
balance or preflight fails replay even if the proposed action is unchanged.
Controllers are single-use, including after failed execution.

Providers passed as Python objects must be operator-trusted code. The HTTP API
and scenario JSON cannot name a provider, import module or executable. This is
not an untrusted-code sandbox. Request/response/recording bounds are 64 KiB,
4 KiB and 3 MiB; 1–32 selected slots and a cumulative requested-gas budget are
enforced. Gas spent on shared setup is reported but is outside that budget.
Trusted providers must impose their own hard response timeout: the branch checks
its 120-second deadline before and after decisions but cannot interrupt an
arbitrary in-process callable. Model generation may be nondeterministic; only
recorded-decision replay is expected to reproduce exactly.

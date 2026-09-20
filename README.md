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

The runner admits only JSON-defined, built-in actions. It does not execute
arbitrary Python, shell commands, downloaded agent code or LLM tool calls.

## EVM verification

### Reading transaction outcomes

Each candidate or baseline trace step has one of four statuses. The source of
truth is [`evm.py`](src/entrotter_engine/evm.py):

| Status | Meaning | `gas_used` | Transaction counters |
| --- | --- | --- | --- |
| `success` | The node accepted the submission, mined it, and the receipt status is successful. | Adds the receipt's gas. | Does not increment either failure counter. |
| `reverted` | The node accepted and mined the transaction, but the receipt reports a revert. | Adds the receipt's gas; reverted transactions still consume gas. | Increments `reverted_transactions`. |
| `rejected` | The node rejected the submission before returning a transaction hash. No receipt is available. | Adds no receipt gas. | Increments `rejected_transactions`. |
| `noop` | The scenario step has no action, so no transaction is submitted. | Remains zero for the step. | Increments neither counter. |

The `gas_used` metric is the sum of receipt gas for `success` and `reverted`
steps. Rejections and no-ops are counted separately from mined transactions.
Native-coin and token balance deltas are raw state changes on the selected
chain, not profit or a portfolio valuation; gas cost is reported separately.

[`tests/data/local.json`](tests/data/local.json) is a synthetic local test
scenario, not historical evidence. The optional
[`test_native_transfer_and_revert`](tests/test_engine.py) test checks a
receipt-bearing success and revert when Anvil is installed; without Anvil it is
skipped. The fixture itself is illustrative input, while a passing test run is
the evidence that those assertions were exercised on that revision.

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

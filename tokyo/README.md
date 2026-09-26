# Tokyo Continuity comparison

New event-period functionality inside the existing Entrotter engine repository. The v0.1 API is unchanged.

```bash
cd tokyo
python3 -m unittest discover -s tests -v
python3 compare.py --block-hash 0xe368c631c74a82c3043e6d44c4bef6e6139a6501b39c7700c2552554d10e6c3b --output report.json
python3 tests/integration.py --anvil /absolute/path/to/anvil --cast /absolute/path/to/cast
```

Requires Python 3.11+ and Foundry 1.8.3. Only local Anvil receives writes. Default public archive: https://eth.drpc.org; set `TOKYO_RPC_URL` privately if needed. No wallet key. Snapshot-restored Uniswap v3 alternatives include actual success, revert and no-transaction hold. Artificial funding, fixed gas price and timestamps are disclosed in the report. Observed state checks are not a Merkle proof. No price prediction, historical replay or PnL claim.

Full submission, prior-work/AI disclosure and measured evidence live in the existing coordination repository under `submission/tokyo2026/` and `evidence/tokyo2026/` on branch `docs/tokyo-continuity`. The viewer lives in the existing website repository at `tokyo2026/` on branch `feat/tokyo-continuity`.

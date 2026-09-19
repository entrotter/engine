# Frozen local agent replay fixture

`agent-recorded-local.json` is a byte-for-byte copy of the public
[recorded local model report](https://github.com/entrotter/entrotter/blob/062cce134ad1e55396587992823654705a669849/evidence/agent-local-codex.json).
Its artifact ID is
`1d1de88d01cbe23c494f6a6f7ee7127d63629baac071def58c067506ddf5893b`.
It originated with engine `bb8b3e8d32c7cbd49629d337758f30bfdf805045`
and Foundry 1.8.3. Preserve the original model/prompt/usage metadata and responses.

The fixture is an artificially funded local transfer/revert example, not a
historical market or evidence of model advantage. Tests replay the recorded
choices against actual current Anvil observations and compare the complete
report, including its content hash. They do not import the recorded provider,
call an LLM, generate new judgments, or use external network in the local worker.
The dedicated native-Anvil and Docker jobs are distinct from stub-based tests.

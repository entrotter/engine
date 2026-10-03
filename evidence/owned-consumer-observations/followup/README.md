# CI failure preservation and focused regression

The first public native CI ran349 tests and failed the existing missing-code
control. A baseline `eth_getTransactionCount` rejection was then hidden by a
two-node cleanup assertion, and later cache checks were skipped. Its original
cause remains unknown; see [initial CI](https://github.com/entrotter/engine/actions/runs/37020975655).

The test helper now checks every actually owned resource before applying expected
node counts. Unexpected primary errors remain intact. Cleanup failure during an
intended cancellation still fails the test. Finite failure diagnostics retain
method/address classes and cache counts without raw request values, URLs or
upstream messages. Production code, scripts and security policy are unchanged.

The [existing missing-code method](ci-evm-focused-after.log) passes1/1.464s,
including two replay-node and one cache closures. A [new actual owned regression](ci-evm-primary-regression-after.log)
passes1/1.302s: an injected baseline-before primary error remains the identical
exception and its one replay-node/cache are closed. Captured diagnostics exclude
the injected private text and URL. These successes do not explain the original
nonce rejection. [Source-bound review and limits](review.json) distinguish this
27-method candidate from the earlier local26-method/full349 evidence. Fresh
whole350-test mandatory CI remains required.

Nine failed GitHub HTML source links now use matching versioned official raw
files; their Git blobs match. Three source line ranges remain explicit in prose.
All eight unique destinations pass the unchanged pinned checker. The initial
isolated job also failed during Docker metadata verification before image build;
the underlying category/cause is unknown. Neither failure is waived. No main
merge, human approval, deployment or execution of the supported historical32
command is claimed.

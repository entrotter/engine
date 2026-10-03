# Bind worker metadata to the actual copied base

Published7b50 passes seven mandatory checks. Native Linux354/83.227s has zero
skips; each Python unit version runs354 with40 declared Anvil skips. Quality
verifies26 sources/all25 reviewed findings,21 exact wheel modules,42 locked
Python identities/zero reported advisories and33 research controls. Docs check20
files/208 links without errors or timeouts. Complete synthetic-merge tree matches
7b50. See the [source-bound prior CI review](ci-partial-7b50-review.json).

The isolated job passes25 real kernel/runtime tests in218.049s and the standard
one/four transaction replays, then fails [base identity verification](ci-isolated-7b50-failed.log).
The [original worker manifest](old-worker-image.json) claims old base011e73b4,
while all22 source/Dockerfile inputs and their digest match7b50 and Dockerfile
pins89281daa. [Independent cause review](child-ci-isolated-7b50-cause-review.json)
confirms build_worker.py still wrote the old base as a constant. The existing
image guard correctly rejected the mismatch before Cosign/Trivy; image and Cargo
audits were not reached. This is separate from prior three package findings.

The builder now derives the base from the actual copied Dockerfile before
launching Docker. Its fixed flat profile requires a single first FROM, the fixed
Chainguard Python repository and64 lowercase digest characters; floating tags,
malformed headers, multiple stages and continued instructions are refused. The
current seven-line Dockerfile fits this profile. No parser acceptance claim is
made for rejected continued spellings. Audit guards, signer/issuer, every-finding
policy, inventory coverage, resource/lifetime and original build bounds remain
unchanged. Manifest source digest still covers all copied module/Dockerfile bytes.

[Before](base-manifest-before.log), two valid pinned-base variants reproduce the
same stale metadata with the actual preparation/copy/hash/manifest flow, a tiny
hash-verified test tar and a simulated Docker command. [After](base-manifest-after.log),
all20 build tests pass5.094s, including18 unchanged tests and two new metadata/
prelaunch rejection controls. Review identified ambiguity in physical lines;
the added split-instruction variant [fails before](base-continuation-before.log)
and both base controls [pass after](base-continuation-after.log) in0.075s, with
all eight invalid variants refused before any Docker launch. These are simulated
build controls, not an actual worker-image/security scan. Existing [seven audit
negative controls](manifest-audit-controls.log) pass as well.

[Final source review](manifest-final-root-review.json) and [independent review](child-manifest-source-review.json)
bind current code/tests/policy and distinguish prefinal evidence. Lint/format/
types26 pass; a full fresh26-source scan retains all25 exact findings and reasons,
zero nosec/skips/errors. Only the builder source digest changes in the review
policy. Parent354/local and Linux results remain historical; new full356-test/
mandatory-eight CI, built-image inventory/signature/Cargo review and supported
historical32 command remain pending. Human main review/deployment/submission are
separate. [Provenance](provenance.json) binds every copy; parent evidence is unchanged.

The independent source review is time-bound: it references earlier root metadata
14611c62, before primary hash aliases were refreshed and prior values moved to
prefinal fields. Current original metadata69f387c1 retains the same final source,
test, policy and scan hashes. The old metadata bytes were not retained and are
not reconstructed. [Provenance](provenance.json) discloses this difference; the
latest independent publication review binds current metadata.

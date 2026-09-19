# Contributing to engine

All code, issues, documentation, and reviews are in English. Small, focused
pull requests are welcome. You do not need cloud accounts or paid API keys
for the offline tests. See [README.md](README.md) for this repository's test command.

1. Fork this public repository and branch from `main`.
2. Check existing issues; describe substantial API changes before implementing.
3. Add a failing regression test, implement the change, and run the tests.
4. Document assumptions, provenance, compatibility, and any skipped checks.
5. Open a PR with the included template. One concern per PR; no unrelated rewrites.

Cross-repository changes: open a tracking issue in `entrotter/entrotter`,
link dependent PRs, and keep compatibility with the existing v0.1 JSON wire
contract. Changes to schemas belong in `entrotter/scenarios`. Breaking changes
need a version bump and migration note. Never add a runtime Git dependency.

Fork PRs run unprivileged tests only. Never use `pull_request_target` to run
contributor code, and never require a contributor to share a wallet key.
Synthetic fixtures must be labelled synthetic. Do not claim benchmark or
historical validation results that have not actually run.

Contributors retain copyright and license contributions under the MIT License.
Be respectful; challenge ideas, not people. Maintainers can remove abusive
content. Publish only material you have permission to share.

Documentation links are checked on every pull request with checksum-pinned
Lychee 0.24.2. The job checks tracked Markdown, HTML and CSS, including hidden
PR templates, relative files and page fragments. Its artifact lists every
result and exclusion. Code examples are not fetched; private/loopback endpoints
are excluded. HTTP errors and timeouts fail the check, including rate limits;
retry after diagnosing the cause instead of accepting an error status.

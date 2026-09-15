# Version 0.2.0 verification

Date: 2026-09-15. Release scope: Linux, Python 3.11+, Codex CLI and/or Claude Code CLI coordinating DeepSeek workers.

## Completed checks

- Development followed regression-first cycles for the new Claude runtime, coordinator-native instruction files, universal CLI/packaging, path-scoped Claude writer permissions and the final `--disallowedTools` capability check. Each new behavior was observed failing before its production change.
- The GitHub Actions matrix runs `PYTHONPATH=src python -m unittest discover -s tests -v` on Python 3.11, 3.12 and 3.13. The final suite contains **128 tests**; two real-Codex protocol tests are skipped on the hosted runner because Codex CLI is not installed there. The remaining synthetic/runtime/Git tests run on every matrix member.
- The matrix builds the 0.2.0 source distribution and `py3-none-any` wheel, installs the wheel, and executes both installed entry points: `codex-deepseek-team --version` and `deepseek-team --version`.
- Existing Codex regression coverage remains in place for provider routing, temporary `CODEX_HOME`, credential isolation/redaction, malformed output handling, bounded read-only retries, unlimited default wait, cancellation, process-group cleanup, read-only/write sandbox configuration and writer result verification.
- Claude runtime tests use a fake Claude Code subprocess and verify the actual child argv/environment boundary: temporary HOME, DeepSeek Anthropic-compatible endpoint, no inherited Anthropic/OAuth/DeepSeek environment credentials, `--bare`, no session persistence, JSON result handling, restricted built-in tools, explicit MCP denial and failure-result suppression.
- Claude writer tests verify that only exact path-scoped `Edit(./file)` permission rules are pre-approved for `--allow-write` targets; read-only mode does not globally pre-approve `Read`. Unsafe permission-rule paths are rejected before inference.
- Coordinator tests verify reversible, byte-preserving managed blocks in `AGENTS.md`, `CLAUDE.md`, or both, including existing file modes and legacy Codex defaults.
- Real Git tests verify clean linked-worktree admission for both `codex/` and `deepseek/` branches, exact post-run file allowlists, ignored/untracked changes, Git index/HEAD/branch integrity, symlink/hardlink rejection, `assume-unchanged`/`skip-worktree` defenses, file-mode changes, filesystem-monitor suppression, external clean/process filter refusal and Git-pointer protection.
- Installer tests verify publication and repeat upgrades of both console aliases without overwriting foreign commands or foreign installation prefixes.
- Offline `doctor` tests verify Codex and Claude capability surfaces independently. Claude-only setup/doctor does not require or modify Codex configuration; `both` preserves the primary Codex model/provider and only manages the package-owned DeepSeek provider block.

## Deliberate limits

- This release remains **Linux-only**. Windows support is intentionally deferred rather than weakening the writer/process/file-safety guarantees.
- The 0.2.0 work did **not** make a live DeepSeek API request and did not execute a real Claude Code or Codex CLI binary in GitHub Actions. Claude protocol tests use a faithful synthetic CLI boundary; the two tests that require a real Codex CLI are explicitly skipped when it is absent. Use `deepseek-team doctor --runtime <codex|claude|both> --live` on the target host for billable end-to-end validation.
- Claude file permissions are an inner boundary and the shared Git verifier is the acceptance boundary. Post-run verification cannot undo arbitrary hostile side effects outside the repository, and this package is not a replacement for an OS user/container confidentiality boundary.
- Codex writer mode still relies on Codex `workspace-write` sandbox behavior plus the shared verifier. Claude writer mode deliberately exposes no Bash/web/agent tools and denies MCP tools, but readable source inside the working environment should still be treated as available to the model.
- The exact writer allowlist permits source creation/editing only in a clean dedicated linked worktree. Rejected or partial changes are preserved for coordinator inspection; writers never automatically retry, stage, commit, push or deploy.
- No speed, token-saving or cost percentage is claimed. Delegation economics depend on task size, supplied context, retries and coordinator review.
- Keys, parent conversation history, primary coordinator auth and raw provider logs are not part of the repository or distributions.

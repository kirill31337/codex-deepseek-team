# DeepSeek Team

- Preserve user changes and credentials; never include keys, local config or raw model logs in Git.
- Codex or Claude Code may be the coordinator. The coordinator owns architecture, security, integration and final verification.
- Delegate bounded independent work to DeepSeek only when it replaces coordinator work. Use the explicit matching runtime (`--runtime codex` or `--runtime claude`).
- Use read-only workers for research/review and `--write` only in an isolated clean linked worktree with exact allowed files.
- Do not duplicate a live worker's assigned investigation. Wait for the full result without an overall timeout; review its actual diff and run meaningful tests.
- Workers must not stage, commit, push, deploy, run builds/tests, or change unrelated files. Writers get one attempt.
- Run tests with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- This repository contains the reusable package only; do not copy unrelated product code, project policies, secrets, or history.

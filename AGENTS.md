# Codex DeepSeek Team

- Preserve user changes and credentials; never include keys, local config or raw model logs in Git.
- The coordinator owns architecture, security, integration and final verification.
- Delegate bounded independent work to DeepSeek where it replaces coordinator work. Use the existing worker, read-only for research/review or --write in an isolated clean worktree with exact allowed files.
- Do not duplicate a live worker’s assigned investigation. Wait for the full result without an overall timeout. Review its actual diff and run meaningful tests.
- Workers must not stage, commit, push, deploy, run builds/tests, or change unrelated files.
- Run tests with PYTHONPATH=src python3 -m unittest discover -s tests -v.
- This repository contains the reusable package only; do not copy unrelated product code, project policies, secrets, or history.

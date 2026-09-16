# DeepSeek Team

- Preserve user changes and credentials; never include keys, local config or raw model logs in Git.
- Codex or Claude Code may be the coordinator. The coordinator owns architecture, security, integration and final verification.
- Delegate bounded independent work to DeepSeek only when it replaces coordinator work. Use the explicit matching runtime (`--runtime codex` or `--runtime claude`).
- Use read-only workers for research/review and `--write` only in an isolated clean linked worktree with exact allowed files.
- The Linux OS sandbox is required for workers. Do not add `--os-sandbox off` to normal/project-managed workflows and do not disable Ubuntu's AppArmor unprivileged-userns restriction globally to make tests pass.
- Codex keeps its native Bubblewrap sandbox; Claude uses the outer DeepSeek Team Bubblewrap policy. Preserve this hybrid boundary unless current upstream behavior is re-verified first.
- Do not duplicate a live worker's assigned investigation. Wait for the full result without an overall timeout; review its actual diff and run meaningful tests.
- Workers must not stage, commit, push, deploy, run builds/tests, or change unrelated files. Writers get one attempt.
- Run tests with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- This repository contains the reusable package only; do not copy unrelated product code, project policies, secrets, or history.

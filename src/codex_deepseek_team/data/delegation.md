## Delegating to DeepSeek workers

- The coordinator owns architecture, security decisions, final diff review, tests and integration.
- Delegate bounded work when its result replaces coordinator work: focused research, review, tests, boilerplate or local implementation. Keep tiny tasks local when delegation would cost more.
- Give each worker a concrete question or acceptance criteria, only necessary files, and a short expected result. Never pass secrets, personal data, host configuration or the full conversation.
- Wait for the full worker result before investigating its assigned area. While it runs, do independent work; afterwards verify its evidence and diff without repeating the entire investigation or rewriting correct code.
- Workers are read-only by default.
- The Linux OS sandbox is required by default. Never add `--os-sandbox off` to managed worker calls. If `deepseek-team sandbox status` fails, fix Bubblewrap/AppArmor setup or continue the task locally instead of weakening containment.
- `--write` requires a clean, dedicated `codex/` or `deepseek/` linked worktree and an exact `--allow-write` file list.
- A writer has one owner per file and one attempt; read-only workers may use bounded retries on actual failures. Workers must not stage, commit, push, deploy, or run builds/tests. The coordinator runs checks.
- Run at most three independent workers sharing the same locks, and do not impose an overall worker timeout. Wait in intervals of up to 60 seconds; silence alone is not a failure and does not authorize duplicate work or cancellation.
- Fall back to coordinator work after a completed runner error, unavailable credentials/runner/sandbox, or `DEEPSEEK_TEAM_DISABLED=1` (`CODEX_DEEPSEEK_DISABLED=1` remains supported); do not repeatedly call a broken provider.
- Review the actual diff, including new files; workers return a short summary instead of copied code.
- Run a worker with: `deepseek-team worker --runtime {runtime}` (the legacy `codex-deepseek-team` command is equivalent).

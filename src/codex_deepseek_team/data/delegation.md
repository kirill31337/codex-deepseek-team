## DeepSeek delegation

Before each new assignment, obtain the CURRENT effective profile, actual access
and value sources (do not rely on a cached level in this file):

```bash
deepseek-team config show --effective --instructions --runtime {runtime}
```

Global/project settings affect new jobs only. The worker enforces the resolved
access at launch and reports it before credential access. Access is independent
of the target delegation level; explicit read-only always remains read-only.

Keep the Linux OS sandbox enabled. Never add `--os-sandbox off` to ordinary worker
commands and never globally disable Ubuntu AppArmor restrictions.

Use `deepseek-team worker --runtime {runtime}` with a bounded goal, acceptance
criteria and enough context. Read-only jobs investigate/review without writes.
Full-access jobs automatically receive their own development copy and may edit
any project files and run prepared local tests/builds. The coordinator prepares
missing dependencies with `workspace create` / `workspace prepare`; do not ask the
user to manually prepare the working copy or enumerate every file.

Existing source dirty/untracked/ignored files are not automatically copied or
cleaned. Review the baseline and explicitly prepare needed source context in the
owned copy. Reuse only an owned `--workspace ID`; inspect partial output before
`--resume-after-failure`. Never retry an uncertain implementation automatically.

The legacy `--write --allow-write FILE` remains available for exact-file changes
in a clean linked worktree. Only that narrow mode forbids tests/builds and requires
an explicit list. Do not combine its flags with the new access flags.

No worker stages, commits, pushes, deploys or publishes. Production databases,
secrets and host services remain coordinator-only. Wait without an overall timeout
unless explicitly requested; silence is not failure. At most three workers may run.

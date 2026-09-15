# Universal package implementation plan

Goal: publish DeepSeek Team as an installable Python package independent of its source application and the chosen primary coordinator. The legacy Python distribution name `codex-deepseek-team` is retained for upgrade compatibility, while the repository and primary CLI are neutral (`deepseek-team`).

Architecture: standard-library Python CLI; existing isolated runner and scoped writer; user-level provider/key setup; managed project instruction block; generic diagnostics. Linux and Python 3.11+ are the initial supported platform.

- [x] Package existing runner, writer and synthetic tests; preserve no total deadline, bounded read-only retries, single writer attempt, clean-worktree checks and private credentials.
- [x] Implement idempotent project init/detach with a marked block in AGENTS.md, preserving all existing bytes outside the managed block and refusing ambiguous or symlinked targets. Tests use temporary Git repositories.
- [x] Implement setup/auth/doctor and CLI entrypoints. Keep the primary model and auth unchanged; diagnostics use synthetic fixtures, no application-specific paths.
- [x] Verify installation in a fresh venv and another synthetic repository, run the complete offline suite and scoped live checks, review final diff and prepare publication via the dedicated SSH key.

Worker-owned interface: project.attach(root: Path) -> bool and project.detach(root: Path) -> bool. True means content changed. Raise ProjectError with a safe explanation for invalid/ambiguous targets. Only project.py, data/delegation.md and test_project.py are delegated; coordinator integrates reviewed diffs.

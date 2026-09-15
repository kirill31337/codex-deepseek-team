# Version 0.1.0 verification

Date: 2026-09-15. Local environment: Linux, Python 3.12, Codex CLI 0.153.4.

## Completed checks

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: **84 tests passed**. Includes the real Codex CLI against a local synthetic Responses fixture, read-only/write sandbox checks, provider routing, bounded retries, unlimited default wait, process cancellation, private credentials, worktree admission/allowlist checks and reversible setup/project instructions.
- `python -m build`: wheel and source distribution built. Package data includes the managed delegation instructions. Build metadata declares MIT and no runtime dependencies.
- Bootstrap installer executed with a separate prefix/bin directory. Installed command exercised `setup`, repeated `setup`/`init`, `doctor --offline`, `detach` and `reset` in an unrelated synthetic Git repository with a separate home. Existing rules, custom primary model and synthetic auth bytes were preserved.
- Final wheel installed into a fresh venv using `pip --no-index`, with `pip check` passing. Its complete package contents matched the source bytes. Project attachment/removal and provider setup/reset passed in another synthetic repository; no checkout imports were available through `PYTHONPATH`.
- Installed `doctor --live`: the API listed and reported `deepseek-flash`; a read-only worker returned evidence from a synthetic repository. Primary configuration/auth and the synthetic repository were unchanged. No overall worker deadline was imposed.
- Installed writer: DeepSeek changed one allowed Python source file and created one allowed unittest file in a clean linked worktree. The coordinator reviewed both files, verified the main checkout was untouched, ran **7 tests**, created a patch including the new file, applied it to the synthetic main checkout and ran those 7 tests there.
- DeepSeek implemented the project instruction module in a separate worktree and reviewed the setup/install/configuration code. The coordinator checked the results, fixed empty-file restoration and ambiguous-block handling, interrupted-install recovery, equivalent installation paths and directory synchronization after writes. Additional regression tests cover these cases and maximum credential length.

## Deliberate limits

- Only Linux is supported initially. Local execution above used Python 3.12; CI is configured for Python 3.11–3.13, but a configured workflow is not evidence of a completed remote run.
- The exact writer file allowlist is verified after execution. Codex provides the workspace sandbox; this package is not a confidentiality boundary against every readable host file.
- Unsafe credential directories and user-edited provider blocks remain refused. Version 0.1.0 has no prior standalone package configuration to migrate; changes to the provider block format in future releases need an explicit migration that preserves user edits.
- No measured combined token-saving percentage or speed improvement is claimed. Savings depend on task size, supplied context, retries and coordinator review. The package supplies delegation instructions and execution controls, not an automatic task router.
- Tests used synthetic code/data. Keys, parent conversation history and raw provider logs are not part of this repository or its distributions.

# Worker boundary hardening (2026-09-15)

This patch strengthens admission and result verification without changing the
coordinator/provider routing, the default unlimited wait, the three-worker limit,
or the single-attempt writer policy. It adds no runtime dependencies.

## Writer verification

Previously, ordinary `git diff` could miss protected-file edits when index entries
used `assume-unchanged` or `skip-worktree`, or when `core.filemode=false` hid an
executable-bit change. Inherited `GIT_INDEX_FILE` could also redirect verification
to a different index. These cases could admit a dirty worktree or accept a change
outside the declared file allowlist.

The verifier now uses a minimal environment, ignores inherited Git overrides and
global/system configuration, forces executable-bit checks, and refuses nonstandard
index flags both before execution and before accepting a result. It does not clear
flags, reset files, or discard the rejected work. The ordinary linked-worktree
`.git` pointer must not be a symlink/hardlink and must remain unchanged.

Verification itself runs outside the Codex sandbox. Repository-configured
`core.fsmonitor` helpers and Git clean/process filters could previously execute
there. Filesystem monitors and hooks are now disabled for verifier commands;
external diff and text conversion are disabled explicitly. Active configured
clean/process filters are detected before running a diff and cause a safe refusal.
Submodule index entries are refused rather than recursively inspected.

### Writer compatibility

Use an ordinary, clean, full linked worktree on a `codex/` branch. Writer mode now
refuses repositories containing submodule entries, nonstandard index flags, or
tracked/allowed files using locally configured external clean/process filters
(including applicable local Git LFS filter configuration). A newly introduced
filter attribute is checked again before the result diff. Other Git attributes,
including an explicitly disabled filter, remain supported when they do not select
an executable filter. Global/system Git settings are not used by the verifier.

Admission failures return 78; detected result violations return 73. Existing
rejected/partial files are preserved for the coordinator to inspect. Do not remove
project features blindly to satisfy these checks; use read-only delegation or do
that task in the coordinator when the worktree is not supported.

The path allowlist is still a **post-execution result check**, not a per-file OS
sandbox. These checks do not prove that arbitrary hostile processes, concurrent
filesystem races, or all readable host files are contained. Stronger isolation
requires a separate OS user/container. No new confidentiality guarantee is made.

## Runtime and output integrity

An environment API key now receives the same basic ASCII/length/whitespace checks
as a saved key, before starting Codex. Invalid values are not printed. An explicit
empty environment key still overrides a saved credential.

The state directory and lock files must be private, owned by the current user,
and of the expected file type. Symlinked directories, FIFO locks, hardlinked locks,
and publicly accessible locks are rejected without changing their permissions or
contents. Normal parallel execution and cancellation retain their existing behavior.

The worker now rejects malformed nonblank JSON event records even if a completed
answer appears elsewhere in the stream. Event types must be nonempty strings;
unknown named event types and blank lines remain forward-compatible. Subprocess
output is decoded after cleanup, and invalid UTF-8 yields a controlled error
instead of a traceback or an accepted partial answer. Failures never publish the
candidate answer. Raw malformed output is not included in the error message.

## Verification

Twenty-five new regression tests cover the cases above. Writer tests use real Git
repositories and linked worktrees, including synthetic executable hooks/filters
that must not run. Runtime tests use fake Codex subprocesses and synthetic keys.
The original worker/writer tests remain unchanged.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The existing GitHub Actions workflow also builds and installs the wheel on Python
3.11, 3.12 and 3.13. No real DeepSeek API request or live Codex sandbox validation
is part of these new tests; those remain separate `doctor --live` checks requiring
a locally configured API key and incurring provider charges.

## References

- Git index flags: https://git-scm.com/docs/git-ls-files
- Attribute inspection: https://git-scm.com/docs/git-check-attr
- Clean/process filters: https://git-scm.com/docs/gitattributes
- Git configuration and filesystem monitors: https://git-scm.com/docs/git-config

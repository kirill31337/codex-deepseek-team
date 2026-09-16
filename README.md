# DeepSeek Team

One Linux package for **Codex and/or Claude Code coordinators** delegating bounded coding work to DeepSeek workers. Workers are read-only by default and can opt into source creation/editing inside a clean linked Git worktree.

**The coordinator owns:** scope, architecture, security decisions, final diff review, tests and integration. **DeepSeek contributes:** focused research, review, boilerplate, tests and bounded implementation. The coordinator should verify the result rather than repeat the entire delegated investigation.

Version **0.3.0** supports **Linux, Python 3.11+, Git, Bubblewrap, and Codex CLI and/or Claude Code CLI**. Ubuntu has first-class AppArmor setup for its restricted unprivileged-user-namespace policy. A DeepSeek API key is required for live work. There are no Python runtime dependencies; Bubblewrap/AppArmor are system components.

## Ubuntu install — recommended

Install the coordinator CLI(s) you intend to use, then:

```bash
git clone https://github.com/kirill31337/deepseek-team.git
cd deepseek-team
python3 install.py --with-sandbox
export PATH="$HOME/.local/bin:$PATH"
deepseek-team sandbox status
```

`--with-sandbox` is an **explicit privileged setup path**. On Ubuntu it installs the `bubblewrap` and `apparmor` packages, installs/reloads the package-owned named profile `deepseek-team-bwrap`, and probes the resulting sandbox. It does **not** disable AppArmor and does **not** change `kernel.apparmor_restrict_unprivileged_userns`.

Then configure whichever coordinator(s) you use:

```bash
# Codex only
deepseek-team setup --runtime codex
deepseek-team doctor --runtime codex --offline
deepseek-team init --coordinator codex

# Claude Code only
deepseek-team setup --runtime claude
deepseek-team doctor --runtime claude --offline
deepseek-team init --coordinator claude

# Or both
deepseek-team setup --runtime both
deepseek-team doctor --runtime both --offline
deepseek-team init --coordinator both
```

The installer creates a dedicated venv at `~/.local/share/codex-deepseek-team/venv` and publishes two equivalent commands:

```text
deepseek-team
codex-deepseek-team   # legacy compatibility alias
```

The legacy Python distribution/namespace is intentionally preserved so existing installations and automation continue to work.

### Rootless/manual install

Plain installation never invokes `sudo`:

```bash
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
deepseek-team sandbox status
```

If `sandbox status` succeeds, no AppArmor change is needed. If Ubuntu blocks Bubblewrap while `kernel.apparmor_restrict_unprivileged_userns=1`, install the package profile explicitly:

```bash
deepseek-team sandbox install-apparmor
deepseek-team sandbox status
```

or rerun `python3 install.py --with-sandbox`.

On other Linux distributions, install Bubblewrap using the distribution package manager and run `deepseek-team sandbox status`. The package-managed AppArmor profile is specifically intended for Ubuntu/AppArmor user-namespace mediation.

**Do not solve Ubuntu failures with** `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. DeepSeek Team intentionally keeps the host restriction enabled and grants user-namespace creation only through its named AppArmor path when that fallback is needed.

You can alternatively use `pipx install .` or a venv, but you still need a working system Bubblewrap backend before workers run.

## Why AppArmor + Bubblewrap

Ubuntu can deny unprivileged applications access to user namespaces unless an AppArmor profile explicitly permits them. DeepSeek Team therefore ships this **named, non-attached** profile:

```text
profile deepseek-team-bwrap flags=(unconfined) {
  userns,
}
```

It is selected explicitly with `aa-exec -p deepseek-team-bwrap -- ...`. The profile does not attach globally to `/usr/bin/bwrap`, so it avoids replacing or competing with distribution/administrator profiles. Its job is only to permit creation of the initial user namespace; **Bubblewrap defines the actual filesystem/process sandbox policy**.

Worker startup is fail-closed by default:

1. locate `bwrap` and verify the required options;
2. try a direct user-namespace probe;
3. if Ubuntu AppArmor blocks direct Bubblewrap and the restriction is active, retry through `aa-exec -p deepseek-team-bwrap`;
4. if neither path works, stop **before reading the DeepSeek credential**.

There is no automatic unsandboxed fallback.

## Codex and Claude use Bubblewrap differently

DeepSeek Team deliberately does **not** put both coordinator CLIs inside the same outer namespace.

### Codex worker

Current Codex on Linux already has its own Bubblewrap-backed `read-only` / `workspace-write` sandbox. Nesting Codex inside another Bubblewrap namespace with further user-namespace creation disabled would break that native sandbox.

DeepSeek Team therefore:

- probes a usable system/AppArmor-aware Bubblewrap backend before worker credentials are read;
- creates a private temporary `bwrap` shim inside the worker session;
- puts that shim first on the worker `PATH`;
- lets **Codex itself** build its normal Linux sandbox using that verified `bwrap` path;
- retains the existing Codex `read-only` / `workspace-write` policy and writer network restrictions;
- runs the shared Git `WriteScope` verifier before accepting a writer result.

The parent Codex auth/history/rules/plugins/apps/memories are not copied; the worker receives a temporary `HOME`/`CODEX_HOME` and only the DeepSeek provider configuration it needs.

### Claude Code worker

Claude Code does not provide the same native Linux Bubblewrap boundary for these built-in file tools, so DeepSeek Team puts the entire isolated Claude worker harness inside an **outer Bubblewrap namespace**:

- read-only root filesystem;
- fresh process/user/IPC/UTS namespaces;
- dropped capabilities;
- private `/tmp` and `/var/tmp`;
- real user HOME masked, with only runtime roots needed to start the CLI re-exposed read-only;
- common credential stores masked again after runtime mounts;
- temporary worker HOME writable;
- repository/worktree mounted read-only for review or read-write for writer mode;
- `--disable-userns` prevents the worker payload from creating another user namespace.

Claude itself still runs `--bare`, with no session persistence. Built-in tools are restricted to `Read,Glob,Grep` for review and `Read,Glob,Grep,Edit,Write` for writer work; Bash, web tools and agents are absent, MCP tools are explicitly denied, and writer approval rules are path-scoped `Edit(./exact/file)` entries.

### Network boundary

The coordinator CLI must reach the DeepSeek API, so the outer Claude Bubblewrap policy intentionally **does not unshare the network namespace**. This release does not claim network isolation. Network-facing model tools remain excluded by the Claude tool surface, while Codex keeps its own sandbox/network policy.

## DeepSeek credential

Both runtimes share the same private DeepSeek credential:

```bash
deepseek-team auth set       # hidden terminal prompt
deepseek-team auth status    # availability only
```

The saved key is `~/.config/codex-deepseek/api-key`, directory mode `700`, file mode `600`. `DEEPSEEK_API_KEY` overrides it. For automation, pipe a secret manager to `deepseek-team auth set --stdin`. Never put a key in command arguments, repository files or worker prompts.

## Project integration

`init` manages one marked instruction block in the coordinator-native file:

- Codex: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- `--coordinator both`: both files

Existing bytes outside the managed block and file permissions are preserved. Managed instructions require the OS sandbox and explicitly tell coordinators **not** to add `--os-sandbox off`; if the sandbox is unavailable, fix it or continue locally.

Re-run `init` after package upgrades to refresh the managed block:

```bash
deepseek-team init --coordinator both /path/to/project
```

## Read-only delegation

Codex:

```bash
deepseek-team worker --runtime codex <<'TASK'
Inspect src/parser.py and tests/test_parser.py.
Find the cause of the empty-input failure. Do not implement changes.
Return concise evidence, suggested fix, risks and tests.
TASK
```

Claude Code:

```bash
deepseek-team worker --runtime claude <<'TASK'
Inspect src/parser.py and tests/test_parser.py.
Find the cause of the empty-input failure. Do not implement changes.
Return concise evidence, suggested fix, risks and tests.
TASK
```

`--runtime auto` prefers Codex when both CLIs are available, otherwise Claude Code. Package-managed instructions use an explicit runtime so coordinator behavior does not silently switch.

## Delegate code creation/editing

Start from a committed baseline and use a **clean linked worktree** on a dedicated `codex/` or `deepseek/` branch:

```bash
git worktree add -b deepseek/parser-fix ../project-deepseek-parser HEAD
cd ../project-deepseek-parser

deepseek-team worker --runtime claude --write \
  --allow-write src/parser.py \
  --allow-write tests/test_parser.py <<'TASK'
Implement the agreed empty-input behavior and add a focused regression test.
Modify only the allowed files. Do not run tests/builds or touch Git state.
Return a brief summary, risks and suggested checks.
TASK
```

The same writer flow works with `--runtime codex`.

The writer gets one attempt, one owner per file, exact allowed paths, a per-worktree lock and post-run Git verification. Hidden/credential targets, symlinks, hardlinks, unsafe index state and unsupported Git filter/submodule configurations are rejected. The verifier checks tracked, untracked and ignored changes plus index, HEAD, branch and the linked-worktree Git pointer. Failed/rejected runs may leave partial work for coordinator inspection; DeepSeek Team never silently resets it.

**The coordinator must inspect the actual diff/new files, run meaningful tests, and integrate.** Workers never stage, commit, push or deploy. Writers never retry automatically after partial edits.

## Sandbox commands

```bash
deepseek-team sandbox status
deepseek-team sandbox install-apparmor
deepseek-team sandbox remove-apparmor
```

`install-apparmor` refuses to overwrite a different/symlinked/non-file `/etc/apparmor.d/deepseek-team-bwrap`. `remove-apparmor` removes the policy only when its installed bytes still exactly match the package copy; administrator-modified policy is preserved.

For diagnosis only, workers accept:

```bash
deepseek-team worker --os-sandbox off ...
```

This prints a warning and deliberately bypasses the new OS-layer requirement. It is **not** used by managed project instructions and should not be used as a fix for a broken production setup.

## Reliability and security boundaries

- At most three workers share user-level locks; writer work also has a per-worktree lock.
- Default total timeout is `0` (unlimited). A slow/silent worker is not treated as failed.
- Read-only transient failures can retry within the configured bounded attempt count. Writers use exactly one attempt.
- Worker output must be a completed structured result. Malformed JSON, invalid UTF-8, terminal failure events and empty successful answers are rejected.
- `DEEPSEEK_TEAM_DISABLED=1` disables delegation. `CODEX_DEEPSEEK_DISABLED=1` remains supported for compatibility.
- DeepSeek/model names in prompts are requested configuration, not proof of the remotely served model; `doctor --live` performs the available routing probe.

Bubblewrap + AppArmor materially tighten host isolation, but DeepSeek Team is **not a complete confidentiality boundary for arbitrary hostile repositories or coordinator binaries**. The Claude sandbox intentionally exposes the worktree and the runtime files required to start the CLI; Codex relies on Codex's native Bubblewrap policy. If the repository itself contains credentials, the model may be allowed to read them as project files. Use a dedicated OS user/container/VM when stronger isolation is required.

## Checks

```bash
deepseek-team sandbox status
deepseek-team doctor --runtime codex --offline
deepseek-team doctor --runtime claude --offline
deepseek-team doctor --runtime both --offline
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`doctor --offline` verifies local sandbox/runtime capabilities without a DeepSeek API request or key validation. `doctor --live` makes billable DeepSeek calls, uses a synthetic repository, and verifies that selected read-only workers do not modify it.

Offline tests use synthetic credentials/transports. GitHub Actions runs the full unittest suite, builds/installs the wheel and exercises both console aliases on Python 3.11, 3.12 and 3.13. A separate Ubuntu job attempts a live Bubblewrap/AppArmor capability smoke test; hosted-runner kernel restrictions are reported separately from deterministic unit-test results. A green CI matrix is not evidence of a live DeepSeek inference request.

## Update and remove

Installer-managed checkout:

```bash
git pull --ff-only
python3 install.py --with-sandbox   # recommended on Ubuntu
deepseek-team init --coordinator both /path/to/project
```

For pipx: `pipx upgrade codex-deepseek-team`, then run `deepseek-team sandbox status`.

Detach project instructions/package-owned coordinator configuration:

```bash
deepseek-team detach --coordinator both /path/to/project
deepseek-team reset --runtime both
deepseek-team auth remove       # optional
```

If you also want to remove only the unchanged package-owned AppArmor policy:

```bash
deepseek-team sandbox remove-apparmor
```

`reset --runtime codex` removes only this package's unmodified DeepSeek provider block and preserves primary auth/model and unrelated providers. Claude runtime has no package-owned persistent provider config, so resetting Claude is a no-op. Environment keys and private Codex config backups are retained.

Uninstall the Python package with your package manager, or remove the installer-owned `~/.local/bin/deepseek-team`, `~/.local/bin/codex-deepseek-team` symlinks and `~/.local/share/codex-deepseek-team` directory after detaching projects.

## Scope

This release remains **Linux-only**. Windows support is deliberately deferred rather than weakening writer guarantees.

## License

[MIT](LICENSE), copyright 2026 kirill31337.

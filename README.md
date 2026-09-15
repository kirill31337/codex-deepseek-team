# DeepSeek Team

One Linux package for **Codex and/or Claude Code coordinators** delegating bounded coding work to isolated DeepSeek workers. Workers are read-only by default and can opt into source creation/editing inside a clean linked Git worktree.

**The coordinator owns:** scope, architecture, security decisions, final diff review, tests and integration. **DeepSeek contributes:** focused research, review, boilerplate, tests and bounded implementation. The coordinator should verify the result rather than repeat the entire delegated investigation.

Version **0.2.0** supports **Linux, Python 3.11+, Git, and Codex CLI and/or Claude Code CLI**. A DeepSeek API key is required for live work. There are no Python runtime dependencies. This is an independent community package.

## Install

Install the coordinator CLI(s) you intend to use, then clone this repository:

```bash
git clone https://github.com/kirill31337/deepseek-team.git
cd deepseek-team
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
```

The installer creates a dedicated venv at `~/.local/share/codex-deepseek-team/venv` and publishes two equivalent commands:

```text
deepseek-team
codex-deepseek-team   # legacy compatibility alias
```

It refuses to overwrite foreign commands. Custom locations are supported with `python3 install.py --prefix ... --bin-dir ...`. You can alternatively use `pipx install .` or install the checkout into your own venv.

## Choose coordinator support

### Codex

```bash
deepseek-team setup --runtime codex
deepseek-team doctor --runtime codex --offline
deepseek-team init --coordinator codex
```

`setup` adds only the DeepSeek provider block to `${CODEX_HOME:-~/.codex}/config.toml`. It does not change the primary Codex model/provider or OpenAI authentication. Existing compatible DeepSeek settings are reused; conflicting settings are refused. Private backups are stored under `codex-deepseek-team-backups` in the Codex home.

### Claude Code

```bash
deepseek-team setup --runtime claude
deepseek-team doctor --runtime claude --offline
deepseek-team init --coordinator claude
```

Claude Code needs **no persistent provider modification**. Each worker gets a temporary HOME and an isolated DeepSeek Anthropic-compatible environment. Parent Claude authentication, OAuth and user configuration are not copied into the worker environment.

### Both

```bash
deepseek-team setup --runtime both
deepseek-team doctor --runtime both --offline
deepseek-team init --coordinator both
```

`init` manages a marked block in the coordinator-native instruction files:

- Codex: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- `both`: both files

Existing bytes outside the managed block and file permissions are preserved. Duplicate/malformed blocks and symbolic-link targets are refused. Re-run `init` after package updates to refresh only the managed block.

## DeepSeek credential

Both runtimes share the same private DeepSeek credential:

```bash
deepseek-team auth set       # hidden terminal prompt
deepseek-team auth status    # availability only
```

The saved key is `~/.config/codex-deepseek/api-key` with directory mode `700` and file mode `600`. `DEEPSEEK_API_KEY` overrides it. For automation, pipe a secret manager to `deepseek-team auth set --stdin`. Never put a key in command arguments, repository files or worker prompts.

## Read-only delegation

Codex runtime:

```bash
deepseek-team worker --runtime codex <<'TASK'
Inspect src/parser.py and tests/test_parser.py.
Find the cause of the empty-input failure. Do not implement changes.
Return concise evidence, suggested fix, risks and tests.
TASK
```

Claude Code runtime:

```bash
deepseek-team worker --runtime claude <<'TASK'
Inspect src/parser.py and tests/test_parser.py.
Find the cause of the empty-input failure. Do not implement changes.
Return concise evidence, suggested fix, risks and tests.
TASK
```

`--runtime auto` prefers Codex when both CLIs are available, otherwise Claude Code. Coordinator-managed instructions always use an explicit runtime so behavior cannot silently switch.

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

The same flow works with `--runtime codex`.

The writer gets one attempt, one owner per file, exact allowed paths, a per-worktree lock and post-run Git verification. Hidden/credential targets, symlinks, hardlinks, unsafe index state and unsupported Git filter/submodule configurations are rejected. The verifier checks tracked, untracked and ignored changes plus index, HEAD, branch and the linked-worktree Git pointer. Failed/rejected runs can leave partial work for coordinator inspection; they are never silently reset.

**The coordinator must inspect the actual diff/new files, run meaningful tests, and integrate.** Workers never stage, commit, push or deploy. Writers never retry automatically after partial edits.

## Runtime isolation

### Codex worker

- Uses provider `deepseek`, model `deepseek-flash`, DeepSeek Responses API.
- Runs a separate ephemeral Codex process with a temporary `CODEX_HOME`.
- Parent Codex auth/history/rules/plugins/apps/memories are not copied.
- Read-only mode uses the Codex read-only sandbox.
- Writer mode uses `workspace-write` with worker network access disabled, then the shared Git allowlist verifier checks the result.

### Claude Code worker

- Uses DeepSeek's Anthropic-compatible endpoint in a separate Claude Code process.
- Uses DeepSeek's current Claude integration mapping `deepseek-flash[1m]` with max effort; DeepSeek currently serves V4.1 Flash.
- Runs `--bare`, print mode, JSON output and no session persistence with a temporary HOME.
- Parent Anthropic API keys/OAuth are not inherited; only the DeepSeek worker token is supplied to the child API client.
- Built-in tool availability is restricted to `Read,Glob,Grep` for review and `Read,Glob,Grep,Edit,Write` for writer work. Bash, web tools and agents are absent from the tool surface; MCP tools are explicitly denied.
- Read-only workers do **not** globally pre-approve `Read`; normal in-worktree reads can proceed while permission-requiring access falls into `dontAsk` and is denied.
- Writers pre-approve only path-scoped `Edit(./exact/file)` rules derived from each `--allow-write` entry. Claude Code applies `Edit(path)` permissions to its built-in write tools as well. Git verification remains the final acceptance boundary.

The package does not claim to be an OS/container confidentiality boundary. Do not delegate repositories containing readable secrets or unrelated private data; use a separate OS user/container when stronger host isolation is required. The exact writer allowlist is both permission-scoped (Claude runtime) and verified after execution, but post-run verification cannot undo arbitrary hostile side effects outside the repository.

## Reliability

- At most three workers share user-level locks; writer work also has a per-worktree lock.
- Default overall timeout is `0` (unlimited). A slow/silent worker is not treated as failed.
- Read-only transient failures can retry within the configured bounded attempt count. Writers use exactly one attempt.
- Worker output must be a completed structured result. Malformed JSON, invalid UTF-8, terminal failure events and empty successful answers are rejected without publishing a candidate answer.
- `DEEPSEEK_TEAM_DISABLED=1` disables delegation. `CODEX_DEEPSEEK_DISABLED=1` remains supported for compatibility.
- DeepSeek/model claims in prompts are treated as requested configuration, not proof of the remote model; `doctor --live` performs the available routing probe.

## Checks

```bash
deepseek-team doctor --runtime codex --offline
deepseek-team doctor --runtime claude --offline
deepseek-team doctor --runtime both --offline
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`--offline` performs no DeepSeek API request and does not validate the key. `doctor --runtime ... --live` makes billable DeepSeek calls, uses a synthetic repository and verifies that the selected read-only runtime does not modify it.

Offline tests use synthetic credentials/transports. The GitHub Actions matrix runs the full unittest suite, builds/installs the wheel and exercises both console aliases on Python 3.11, 3.12 and 3.13. Real local CLI protocol tests run only when the corresponding CLI is available; a green synthetic matrix is not evidence of a live provider request.

## Update, disable and remove

Installer-managed checkout:

```bash
git pull --ff-only
python3 install.py
deepseek-team init --coordinator both /path/to/project   # choose codex/claude/both as needed
```

For pipx: `pipx upgrade codex-deepseek-team`.

Detach project instructions and package-owned configuration:

```bash
deepseek-team detach --coordinator both /path/to/project
deepseek-team reset --runtime both
deepseek-team auth remove       # optional
```

`reset --runtime codex` removes only this package's unmodified provider block and preserves primary auth/model and unrelated providers. Claude runtime has no package-owned persistent provider config, so resetting Claude is intentionally a no-op. Environment keys and private Codex config backups are retained.

Uninstall with your package manager, or remove the installer-owned `~/.local/bin/deepseek-team`, `~/.local/bin/codex-deepseek-team` symlinks and `~/.local/share/codex-deepseek-team` directory after detaching projects.

## Scope

This release remains **Linux-only**. Windows support is deliberately deferred rather than weakening writer guarantees.

## License

[MIT](LICENSE), copyright 2026 kirill31337.

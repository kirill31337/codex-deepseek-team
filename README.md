# Codex DeepSeek Team

Keep Codex in charge and delegate bounded work to DeepSeek. An installable CLI for independent projects, with read-only workers and optional implementation in isolated Git worktrees.

**Codex coordinates:** scope, architecture, security, final review, tests and integration. **DeepSeek contributes:** focused research, review, boilerplate and local implementation. Delegation should replace work the coordinator would otherwise do; review the result without repeating the whole investigation or rewriting correct code.

Initial support: **Linux, Python 3.11+, Git and Codex CLI**. The runner is tested with Codex CLI **0.153.4**. A DeepSeek API key is required for live work. There are no Python runtime dependencies. This is an independent community package.

## Install

Install and authenticate Codex CLI first. Then clone this repository and run:

```bash
git clone https://github.com/kirill31337/codex-deepseek-team.git
cd codex-deepseek-team
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
codex-deepseek-team setup
codex-deepseek-team doctor --offline
```

The installer creates a dedicated venv at `~/.local/share/codex-deepseek-team/venv` and the command `~/.local/bin/codex-deepseek-team`. It refuses to overwrite another installation's command. Python's venv/pip support and network access for build dependencies are needed. Keep `~/.local/bin` in your shell's PATH. Custom locations: `python3 install.py --prefix /path/to/installation --bin-dir /path/to/bin`.

Alternatively, install the checkout with `pipx install .`, or `python -m pip install .` inside your own virtual environment. This release is distributed through GitHub; no PyPI publication is assumed.

`setup` adds a DeepSeek provider to `${CODEX_HOME:-~/.codex}/config.toml` without changing the primary model, provider or OpenAI authentication. Existing compatible DeepSeek settings are reused; conflicting settings are refused. Changes get private backups under `codex-deepseek-team-backups` in that Codex home. Use `setup --no-key` to skip the hidden key prompt.

### Credential

```bash
codex-deepseek-team auth set       # hidden terminal prompt
codex-deepseek-team auth status    # availability only
```

The saved key is `~/.config/codex-deepseek/api-key`, directory mode `700`, file mode `600`. `DEEPSEEK_API_KEY` overrides it. For automation, pipe a secret manager's output to `codex-deepseek-team auth set --stdin`; never put a key in a command argument, repository or task prompt.

## Connect a project

From the root of any Git repository:

```bash
codex-deepseek-team init
```

This adds one managed instruction block to `AGENTS.md`. Existing content and file permissions are preserved. Run it again to refresh that block after an update; keep your own instructions outside the markers. Duplicate, malformed or symlinked targets are refused. Commit the instructions if you want to share them with collaborators. Remove conflicting old project instructions, such as a blanket ban on all writer work, when adopting this workflow.

The package supplies a runner and delegation instructions. The coordinator still chooses and invokes tasks; it is not an automatic task router and does not replace the main Codex model. Restart the Codex task if it has already loaded older project instructions.

## Read-only research or review

```bash
codex-deepseek-team worker <<'TASK'
Inspect only src/parser.py and tests/test_parser.py.
Find the cause of the described empty-input failure. Do not implement changes.
Return the relevant file/line evidence, suggested fix, risks and tests, in at most 500 words.
TASK
```

Give one bounded question, necessary files and a short expected result. Wait for the complete answer before investigating that area yourself. Do independent work while waiting; then verify the evidence. Tiny edits often cost less to do directly. There is no delegation quota or guaranteed savings percentage.

## Delegate implementation

Start from a committed baseline. Create a **clean linked worktree** on a dedicated `codex/` branch:

```bash
git worktree add -b codex/deepseek-parser ../project-deepseek-parser HEAD
cd ../project-deepseek-parser
codex-deepseek-team worker --write \
  --allow-write src/parser.py \
  --allow-write tests/test_parser.py <<'TASK'
Implement the agreed empty-input behavior in src/parser.py and a focused regression
test in tests/test_parser.py. Modify only these files. Do not run tests or builds.
Do not stage, commit or push. Return a short summary, risks and suggested checks.
TASK
```

The writer gets one attempt, one owner per file, exact allowed paths, a per-worktree lock and a workspace-write sandbox with network disabled. Hidden files, credentials, symlinks, hardlinks and unsafe worktrees are rejected. It may create missing allowed source files. The runner checks tracked, untracked and ignored changes plus the Git index, HEAD and branch before reporting success. A failed/rejected run can leave partial changes in the worktree; inspect them before another action.

**Codex must review the actual diff and new files, run suitable tests, and integrate.** Workers never stage, commit, push, deploy or run builds/tests. For a patch including new files, the coordinator can mark only approved files with `git add -N -- <paths>`, create `git diff --binary HEAD -- <paths>`, review it, and apply it with `git apply --check` followed by `git apply` in the destination. Check the destination's status first and preserve other work. A worktree's normal `git diff` alone omits untracked new files.

## Reliability and isolation

- Provider `deepseek`, model `deepseek-flash`, Responses endpoint `https://api.deepseek.com`. The main model is untouched. Routing uses a separate Codex process, not native cross-provider child roles.
- A temporary worker `CODEX_HOME` excludes parent history, auth, rules, plugins and MCP servers. The worker does not inherit arbitrary environment variables. Credentials are available to its Codex API client, excluded from model shell commands. Do not put secrets in task input or accessible project files.
- Read-only mode denies writes. Writer mode confines writes to its worktree through the Codex sandbox. **The exact file allowlist is checked after execution; it is not a per-file OS sandbox.** A worktree and sandbox do not guarantee confidentiality of every readable host file. Use trusted scoped source code; use a separate OS user/container for stronger isolation.
- At most three workers share user-level locks. Writer work has an additional worktree lock. The default overall timeout is **0 (unlimited)**. Read-only failures have bounded retries; writers never retry automatically. A slow or silent worker is not a failed worker. Wait in intervals of up to 60 seconds; do not impose an external deadline unless the owner requested one.
- Only fall back after an actual completed failure, missing runner/key or `CODEX_DEEPSEEK_DISABLED=1`. The caller owns that decision; the package does not launch a second coordinator job. Print and retain only compact results, not private prompts or raw API logs.
- Inherited worker environment switches use the `CODEX_DEEPSEEK_` prefix for compatibility with earlier runner installations. Inspect `codex-deepseek-team worker --help` for execution and scope options. Budgets limit worker effort, not combined coordinator/provider billing.

## Checks

```bash
codex-deepseek-team doctor --offline  # local provider + CLI checks; no API requests
codex-deepseek-team doctor --live     # paid API routing probe + synthetic read-only worker
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Live checks use a temporary synthetic repository and verify it was not modified. They require an API key and make billable DeepSeek requests. Offline tests use synthetic credentials and fake transports; local protocol/sandbox tests run the real Codex CLI if it is installed. These tests do not prove compatibility with every Codex release or third-party project.

## Update, disable and remove

For an installer-managed checkout:

```bash
git pull --ff-only
python3 install.py
codex-deepseek-team init /path/to/project
```

For pipx, use `pipx upgrade codex-deepseek-team`; for a venv install, use `python -m pip install --upgrade /path/to/checkout`.

Disable worker calls with `export CODEX_DEEPSEEK_DISABLED=1`. To detach a project and remove this package's configuration:

```bash
codex-deepseek-team detach /path/to/project
codex-deepseek-team reset
codex-deepseek-team auth remove       # optional: delete the saved DeepSeek key
```

`detach` restores content outside its block, including a pre-existing empty file. `reset` removes only this package's unmodified provider block and keeps primary auth and saved keys. A pre-existing provider is not owned by this package and is retained. The saved key location is shared with older `codex-deepseek-worker` installations, so removing it affects those users too. Environment keys and private config backups are retained.

Uninstall with your package manager, or remove the installer-owned `~/.local/bin/codex-deepseek-team` symlink and `~/.local/share/codex-deepseek-team` directory after detaching projects. An existing `codex-deepseek-worker` command is not overwritten by this package.

## License

[MIT](LICENSE), copyright 2026 kirill31337.

# AppArmor + Bubblewrap Worker Isolation Design

## Goal

Add a Linux OS-level containment layer around every DeepSeek worker process, with first-class Ubuntu AppArmor support, without weakening the existing Codex/Claude runtime restrictions or Git writer verification.

## Security model

`deepseek-team worker` runs the selected Codex or Claude Code harness inside Bubblewrap (`bwrap`) by default. Bubblewrap is a second containment boundary around the existing runtime-specific controls:

- Codex keeps its own `read-only` / `workspace-write` sandbox and DeepSeek provider configuration.
- Claude Code keeps `--bare`, restricted built-in tools, path-scoped writer permissions, no Bash/web/agents, and explicit MCP denial.
- `WriteScope` remains authoritative for accepting writer results and still verifies HEAD, branch, index and changed paths after execution.
- Bubblewrap adds mount/process/user/IPC/UTS isolation, drops capabilities, creates private temporary directories and hides the real user home from the worker except for the minimum runtime paths needed to start the selected CLI.

The outer Bubblewrap layer must not silently disappear. Worker execution is fail-closed by default when a usable Bubblewrap sandbox cannot be created. A deliberately explicit `--os-sandbox off` escape hatch remains available for diagnosis/legacy environments and prints a warning; coordinator-managed instructions never use it.

## Bubblewrap layout

The worker child is launched with a command equivalent to:

- `--die-with-parent`
- `--new-session`
- `--unshare-user`
- `--unshare-pid`
- `--unshare-ipc`
- `--unshare-uts`
- `--unshare-cgroup-try` when supported
- `--disable-userns`
- `--cap-drop ALL`
- root filesystem mounted read-only
- a fresh `/proc`
- a minimal `/dev`
- private tmpfs mounts for `/tmp` and `/var/tmp`
- the per-worker temporary HOME mounted read-write
- the current repository/worktree mounted read-only for research/review and read-write for writer mode
- the real user HOME hidden by tmpfs; only runtime roots required by the resolved coordinator executable/PATH are re-exposed read-only, followed by explicit masks for common credential stores

The runtime API client still needs outbound network access to reach DeepSeek. Therefore the outer Bubblewrap layer intentionally keeps the host network namespace. Network capability for model tools remains controlled by the existing harness rules: Claude exposes no Bash/web tools, and Codex keeps its own sandbox network restrictions. Documentation must not claim that Bubblewrap provides network isolation.

## Ubuntu AppArmor integration

Ubuntu 24.04+ enables AppArmor mediation of unprivileged user namespace creation by default. Globally setting `kernel.apparmor_restrict_unprivileged_userns=0` is forbidden by this package.

To avoid collisions with distribution or third-party `/usr/bin/bwrap` attachment profiles, DeepSeek Team ships a named profile `deepseek-team-bwrap` rather than a global `profile ... /usr/bin/bwrap` attachment. The profile is selected only for our Bubblewrap invocation through:

```text
aa-exec -p deepseek-team-bwrap -- /usr/bin/bwrap ...
```

The profile itself is intentionally narrow in purpose: it is unconfined for ordinary resources and grants `userns` so Bubblewrap can construct the namespace. The actual sandbox restriction comes from Bubblewrap. `--disable-userns` prevents the worker payload from creating further user namespaces after setup.

Runtime selection is capability based:

1. Probe direct `bwrap` first. If it works, use it and do not interfere with existing distro policy.
2. If direct `bwrap` is blocked and AppArmor unprivileged-userns restriction is active, probe the package named profile through `aa-exec`.
3. If neither path works, fail closed and print remediation instructions.

This avoids overwriting or disabling Ubuntu's own `bwrap-userns-restrict` policy and avoids changing global sysctls.

## System setup and removal

A new sandbox helper module owns probing, command construction and AppArmor lifecycle operations.

`deepseek-team sandbox status` reports:

- Bubblewrap path/version and required option support;
- `kernel.apparmor_restrict_unprivileged_userns` when present;
- whether direct Bubblewrap works;
- whether the package AppArmor profile path works through `aa-exec`;
- the effective backend selected for workers.

`deepseek-team sandbox install-apparmor` installs only the package-owned profile and loads it with `apparmor_parser -r`. It may invoke `sudo`; it refuses to replace an existing different profile file.

`deepseek-team sandbox remove-apparmor` unloads/removes only a byte-for-byte package-owned profile and refuses to remove modified administrator policy.

On Ubuntu, `python3 install.py --with-sandbox` additionally ensures the required system packages are present and installs/loads the named profile. Plain `python3 install.py` remains non-root and package-only, but prints a clear sandbox remediation when the required worker sandbox is not usable.

## Compatibility

- Linux and Python 3.11+ remain required.
- Codex and Claude Code runtime interfaces remain unchanged.
- Existing credential locations, environment switches and the legacy `codex-deepseek-team` command remain compatible.
- The release version becomes `0.3.0` because worker execution now has a new mandatory outer sandbox by default.
- No Python runtime dependency is added; Bubblewrap/AppArmor are system dependencies.
- Non-Ubuntu Linux can use direct Bubblewrap without AppArmor-specific installation.

## Error handling

Sandbox setup errors must never include environment values or raw provider output. Worker execution must stop before reading the DeepSeek credential when required OS isolation is unavailable. Timeouts/cancellation must continue to kill the whole process group, including `aa-exec`/`bwrap` and the coordinator CLI.

System installation is conservative: no global sysctl edits, no replacement of foreign AppArmor profiles, no automatic deletion of modified policy, and no fallback from a requested secure worker to unsandboxed execution.

## Testing

Regression-first tests cover:

- direct Bubblewrap backend selection;
- AppArmor `aa-exec` fallback selection;
- fail-closed behavior when neither works;
- required Bubblewrap flags and read-only/read-write worktree mounting;
- real HOME masking and temporary HOME binding;
- runtime paths under HOME re-exposed read-only;
- credential-store masks ordered after runtime mounts;
- worker stopping before key reads when sandbox setup fails;
- both Codex and Claude commands wrapped identically by the outer sandbox;
- installer `--with-sandbox` behavior through mocked privileged commands;
- AppArmor install/remove refusal for foreign or modified files;
- package data includes the AppArmor profile;
- doctor/sandbox status output does not expose credentials;
- full existing 0.2 regression suite remains green.

CI additionally performs a Bubblewrap smoke test on Ubuntu when the runner supports unprivileged user namespaces; the deterministic unit tests remain authoritative when a hosted kernel does not expose AppArmor/userns capabilities.

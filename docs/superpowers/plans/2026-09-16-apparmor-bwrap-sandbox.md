# AppArmor + Bubblewrap Worker Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every DeepSeek worker inside a fail-closed Bubblewrap sandbox and provide collision-safe Ubuntu AppArmor setup for unprivileged user namespaces.

**Architecture:** Add a focused `sandbox.py` module that probes Bubblewrap/AppArmor capabilities, constructs the outer sandbox command, and manages the package-owned named AppArmor profile. `worker.py` delegates process wrapping to that module while preserving Codex/Claude restrictions and `WriteScope`; CLI/installer expose status/install/remove operations and README documents Ubuntu setup.

**Tech Stack:** Python 3.11+ stdlib, Linux namespaces, Bubblewrap, AppArmor/aa-exec, unittest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-16-apparmor-bwrap-sandbox-design.md`

## Global Constraints

- Linux and Python 3.11+ only.
- No Python runtime dependencies.
- Bubblewrap is required by default for workers; only explicit `--os-sandbox off` bypasses it.
- Never modify `kernel.apparmor_restrict_unprivileged_userns` or other global userns sysctls.
- Never overwrite or remove foreign/administrator-modified AppArmor policy.
- Direct working Bubblewrap always wins over package AppArmor fallback.
- API network remains available to the coordinator CLI; do not claim outer network isolation.
- Existing Codex/Claude controls and Git writer verification remain mandatory.
- Writers still get one attempt and never stage/commit/push/deploy/run tests.

---

### Task 1: Bubblewrap/AppArmor capability layer

**Files:**
- Create: `src/codex_deepseek_team/sandbox.py`
- Create: `src/codex_deepseek_team/data/apparmor/deepseek-team-bwrap`
- Create: `tests/test_sandbox.py`
- Modify: `pyproject.toml`
- Modify: `MANIFEST.in`

**Interfaces:**
- Produces: `SandboxError(code: int, message: str)`
- Produces: `SandboxBackend(prefix: tuple[str, ...], bwrap: str, source: str)`
- Produces: `apparmor_restriction() -> int | None`
- Produces: `probe_backend() -> SandboxBackend`
- Produces: `wrap_command(command, *, cwd: Path, session_home: Path, writable: bool, env: dict[str, str], backend: SandboxBackend) -> list[str]`
- Produces: `install_apparmor(*, use_sudo: bool = True) -> bool`
- Produces: `remove_apparmor(*, use_sudo: bool = True) -> bool`

- [ ] **Step 1: Write failing sandbox tests**

Add tests that patch `shutil.which`/`subprocess.run` and assert direct bwrap is preferred, `aa-exec -p deepseek-team-bwrap --` is the fallback when direct probing fails under AppArmor restriction, and both failure paths raise `SandboxError(78, ...)`. Add command-construction assertions for `--die-with-parent`, `--new-session`, `--unshare-user`, `--unshare-pid`, `--unshare-ipc`, `--unshare-uts`, `--disable-userns`, `--cap-drop ALL`, root `--ro-bind / /`, `/proc`, `/dev`, private tmpfs, HOME masking, runtime-path rebinds and final worktree bind mode.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_sandbox -v
```

Expected: import/attribute failures because `codex_deepseek_team.sandbox` does not exist.

- [ ] **Step 3: Add the package-owned AppArmor profile**

Create:

```text
abi <abi/4.0>,
include <tunables/global>

profile deepseek-team-bwrap flags=(unconfined) {
  userns,
  include if exists <local/deepseek-team-bwrap>
}
```

The profile has no executable attachment; workers select it explicitly with `aa-exec` only when direct bwrap is blocked.

- [ ] **Step 4: Implement backend probing**

Implement direct `bwrap` probe first using a bounded command similar to:

```python
[bwrap, '--die-with-parent', '--new-session', '--unshare-user', '--unshare-pid',
 '--disable-userns', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
 '/usr/bin/true']
```

Require `--disable-userns`, `--new-session`, `--die-with-parent` and `--unshare-user` in `bwrap --help`. If direct probe fails and `/proc/sys/kernel/apparmor_restrict_unprivileged_userns` is `1`, retry through `aa-exec -p deepseek-team-bwrap --`. Do not inspect or print child environment values.

- [ ] **Step 5: Implement mount layout**

Build the sandbox argv without moving secrets into argv. Keep the already-sanitized environment in `subprocess.Popen(env=...)`. Hide the real `Path.home()` with tmpfs, re-expose only top-level runtime roots needed by the resolved command/PATH read-only, then mask known credential locations (`.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.docker`, `.codex`, `.claude`, `.config` when not needed by runtime, `.local/share/keyrings`, `.netrc`, `.git-credentials`, `.npmrc`, `.pypirc`). Re-bind the per-worker temporary HOME read-write and repository/worktree last.

- [ ] **Step 6: Implement conservative AppArmor lifecycle**

Resolve the packaged profile with `importlib.resources`. `install_apparmor()` refuses a different existing `/etc/apparmor.d/deepseek-team-bwrap`, otherwise uses `install -m 0644` and `apparmor_parser -r`. `remove_apparmor()` compares installed bytes to packaged bytes before unloading with `apparmor_parser -R` and deleting it. Privileged commands are optionally prefixed with `sudo`.

- [ ] **Step 7: Package the profile**

Update `pyproject.toml` package data to include `data/apparmor/*` and `MANIFEST.in` with `recursive-include src/codex_deepseek_team/data/apparmor *`.

- [ ] **Step 8: Run focused tests to GREEN**

```bash
PYTHONPATH=src python3 -m unittest tests.test_sandbox -v
```

Expected: all sandbox tests pass.

---

### Task 2: Put Codex and Claude workers behind the outer sandbox

**Files:**
- Modify: `src/codex_deepseek_team/worker.py`
- Modify: `tests/test_codex_deepseek_worker.py`
- Modify: `tests/test_claude_runtime.py`
- Create: `tests/test_worker_os_sandbox.py`

**Interfaces:**
- Consumes: `sandbox.probe_backend()` and `sandbox.wrap_command(...)`
- Produces CLI flag: `--os-sandbox {required,off}`, default `required`

- [ ] **Step 1: Write failing worker integration tests**

Tests must prove that required sandbox failure occurs before `load_api_key()`, both runtime commands are passed through `sandbox.wrap_command`, writer/read-only mode maps to `writable=True/False`, and `--os-sandbox off` is the only path that calls the runtime command directly. Add an assertion that Codex worker HOME becomes the temporary session HOME instead of the caller's real HOME.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker_os_sandbox tests.test_claude_runtime tests.test_codex_deepseek_worker -v
```

Expected: failures for missing `--os-sandbox` and missing sandbox integration.

- [ ] **Step 3: Integrate sandbox selection before credentials**

In `run_worker`, resolve the coordinator executable, select/probe Bubblewrap when policy is `required`, and only then call `load_api_key()`. Keep `DEEPSEEK_TEAM_DISABLED=1` as the earliest exit. Import `sandbox.py` with the same safe sibling-module pattern used for `write_scope.py` so direct script execution still works.

- [ ] **Step 4: Wrap execution command**

Inside the per-worker temporary directory, set `HOME` to that directory for both Codex and Claude. Build the existing runtime command unchanged, then replace it with `sandbox.wrap_command(...)` before `execute()`. Writer verification still runs after the child exits and before its answer is accepted.

- [ ] **Step 5: Add explicit bypass semantics**

`--os-sandbox off` prints one concise stderr warning before running the legacy runtime path. No automatic fallback from `required` is permitted.

- [ ] **Step 6: Run worker suites to GREEN**

```bash
PYTHONPATH=src python3 -m unittest tests.test_worker_os_sandbox tests.test_claude_runtime tests.test_codex_deepseek_worker tests.test_codex_deepseek_write tests.test_worker_hardening tests.test_write_scope_hardening -v
```

Expected: all pass, with existing real-Codex conditional skips unchanged where Codex is unavailable.

---

### Task 3: Sandbox CLI, doctor and Ubuntu-aware installer

**Files:**
- Modify: `src/codex_deepseek_team/cli.py`
- Modify: `src/codex_deepseek_team/doctor.py`
- Modify: `install.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_universal_cli.py`
- Modify: `tests/test_install.py`
- Create: `tests/test_sandbox_cli.py`

**Interfaces:**
- Produces: `deepseek-team sandbox status`
- Produces: `deepseek-team sandbox install-apparmor`
- Produces: `deepseek-team sandbox remove-apparmor`
- Produces installer flag: `python3 install.py --with-sandbox`

- [ ] **Step 1: Write failing CLI/installer tests**

Assert sandbox subcommands dispatch to `sandbox` lifecycle functions, `doctor --offline` reports the selected Bubblewrap backend and fails with exit 78 when required containment is unavailable, and `install.py --with-sandbox` invokes the installed venv command for Ubuntu system setup while plain installation never runs privileged package/profile changes.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python3 -m unittest tests.test_sandbox_cli tests.test_cli tests.test_universal_cli tests.test_install -v
```

Expected: parser/dispatch failures because sandbox commands/installer flag do not yet exist.

- [ ] **Step 3: Add `sandbox` command group**

Add the three subcommands. `status` prints no secret values. Install/remove surface `SandboxError` as exit 78. Do not mix sandbox setup into coordinator auth/config setup.

- [ ] **Step 4: Extend doctor**

`doctor` runs the local Bubblewrap capability check before coordinator-specific CLI checks and reports whether it selected direct bwrap or the AppArmor `aa-exec` fallback. Live tests inherit the exact same required outer sandbox.

- [ ] **Step 5: Extend installer**

Add `--with-sandbox`. After the venv and entrypoints exist, detect Ubuntu from `/etc/os-release`; when requested, install missing `bubblewrap` and `apparmor` packages through `sudo apt-get install -y`, then invoke the installed `deepseek-team sandbox install-apparmor` and `deepseek-team sandbox status`. Plain install remains rootless. On Ubuntu with the AppArmor userns restriction active and no usable backend, plain install prints the exact secure follow-up command instead of disabling the sysctl.

- [ ] **Step 6: Run CLI/installer suites to GREEN**

```bash
PYTHONPATH=src python3 -m unittest tests.test_sandbox_cli tests.test_cli tests.test_universal_cli tests.test_install -v
```

Expected: all pass.

---

### Task 4: Managed instructions, docs, release metadata and CI smoke

**Files:**
- Modify: `src/codex_deepseek_team/data/delegation.md`
- Modify: `README.md`
- Modify: `docs/HARDENING.md`
- Modify: `docs/VERIFICATION.md`
- Modify: `pyproject.toml`
- Modify: `src/codex_deepseek_team/__init__.py`
- Modify: `.github/workflows/test.yml`
- Modify: `tests/test_universal_cli.py`
- Modify: `tests/test_coordinators.py`

**Interfaces:**
- Version: `0.3.0`

- [ ] **Step 1: Write failing release/instruction assertions**

Assert version `0.3.0`, package metadata includes AppArmor data, and managed delegation text states the OS sandbox is required and must not be disabled by coordinators.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python3 -m unittest tests.test_universal_cli tests.test_coordinators -v
```

Expected: version/instruction assertions fail against 0.2.0 documentation.

- [ ] **Step 3: Update docs and metadata**

README Ubuntu quick path becomes:

```bash
git clone https://github.com/kirill31337/deepseek-team.git
cd deepseek-team
python3 install.py --with-sandbox
export PATH="$HOME/.local/bin:$PATH"
deepseek-team doctor --runtime both --offline
```

Also document rootless install + later `sandbox install-apparmor`, direct distro-profile compatibility, the named-profile collision avoidance, `--os-sandbox off` as an explicit unsafe escape hatch, the preserved network requirement, and the rule never to disable `kernel.apparmor_restrict_unprivileged_userns` globally.

- [ ] **Step 4: Add CI Bubblewrap smoke**

Keep the Python 3.11-3.13 matrix. Add one Ubuntu 24.04 smoke job/step that installs Bubblewrap if needed and runs a non-network synthetic sandbox probe; if the hosted kernel lacks the relevant namespace capability, report that as an explicit skipped environment capability rather than treating unit tests as proof of AppArmor enforcement.

- [ ] **Step 5: Run the complete suite and build**

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python -m build
python -m pip install dist/*.whl
codex-deepseek-team --version
deepseek-team --version
```

Expected: full suite passes, wheel/sdist build succeeds, both commands print `deepseek-team 0.3.0`.

- [ ] **Step 6: Review branch diff and CI**

Compare the feature branch against `main`; only sandbox/profile/tests/docs/release metadata should change. Require the Python 3.11/3.12/3.13 jobs to be green before fast-forwarding `main`. Record exact limitations in `docs/VERIFICATION.md`, especially whether a real AppArmor-enforced `aa-exec` path was exercised or only unit-tested.

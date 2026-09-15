"""Admission and result checks for an explicitly scoped, isolated worktree writer.

The CLI sandbox bounds writes to the worktree. The path allowlist is a result
check, not a per-file OS sandbox. Rejected/partial changes are never discarded.
"""
import fcntl
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


class ScopeError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def git(*args, input=None, ok=(0,)):
    # Verification runs outside the model sandbox. Do not inherit repository/index
    # overrides, credentials or executable filesystem-monitor hooks from the caller.
    allow = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TZ'}
    env = {name: value for name, value in os.environ.items() if name in allow}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0',
               GIT_NO_REPLACE_OBJECTS='1')
    result = subprocess.run(
        ['git', '-c', 'core.fsmonitor=false', '-c', 'core.filemode=true',
         '-c', 'core.ignoreStat=false', '-c', 'core.trustctime=true',
         '-c', 'core.hooksPath=' + os.devnull,
         '-c', 'core.attributesFile=' + os.devnull, *args],
        input=input, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode not in ok:
        raise ScopeError(78, 'Cannot verify the writer worktree; the coordinator must inspect it.')
    return result.stdout


class WriteScope:
    def __init__(self, paths):
        self.root = Path.cwd().resolve()
        self.paths = set(paths)
        self.lock = None

    def validate_path(self, name):
        path = PurePosixPath(name)
        forbidden = {'secrets', 'credentials', 'signing', 'auth.json', 'api-key',
                     'store-password', 'key-alias', 'id_rsa', 'id_ed25519'}
        if (not name or path.is_absolute() or str(path) != name or
                any(p.startswith('.') or p.lower() in forbidden for p in path.parts) or
                any(c in name for c in '*?[]\\\n\r\0') or
                path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx', '.jks', '.keystore'}):
            raise ScopeError(78, 'Write paths must be exact relative source files, without secrets, metadata or traversal.')
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise ScopeError(78, 'Symlinks are not allowed in writer paths.')
        if current.exists():
            info = current.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ScopeError(78, 'Writer targets must be ordinary files without hard links.')

    def git_pointer(self, code):
        try:
            fd = os.open(self.root / '.git', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError('unsafe pointer')
                pointer = source.read(4097)
                if len(pointer) > 4096:
                    raise OSError('oversized pointer')
                return pointer
        except OSError:
            raise ScopeError(code, 'Writer requires an ordinary .git pointer without symbolic or hard links; work retained for inspection.') from None

    def verify_index_flags(self, code):
        # Git diff deliberately trusts assume-unchanged / skip-worktree entries.
        # Fail closed instead of clearing flags or silently losing existing work.
        entries = git('ls-files', '-v', '-z').split(b'\0')
        if any(entry and not entry.startswith(b'H ') for entry in entries):
            raise ScopeError(code, 'Writer cannot verify assume-unchanged, skip-worktree or unmerged index entries; use a clean full worktree.')

    def verify_checkout_features(self, code):
        entries = git('ls-files', '--stage', '-z').split(b'\0')
        if any(entry.startswith(b'160000 ') for entry in entries):
            raise ScopeError(code, 'Writer does not support submodule entries; recursive Git checks may execute helpers outside the sandbox.')
        # Even --name-only / --no-ext-diff can invoke clean/process filters.
        # Inspect names only, never configured commands (which may contain secrets).
        configured = git('config', '--null', '--name-only', '--get-regexp',
                         r'^filter\..*\.(clean|process)$', ok=(0, 1))
        drivers = {name[7:].rsplit(b'.', 1)[0]
                   for name in configured.split(b'\0') if name}
        if not drivers:
            return
        paths = [entry.partition(b'\t')[2] for entry in entries if entry]
        paths.extend(os.fsencode(name) for name in sorted(self.paths))
        attributes = git('check-attr', '--all', '-z', '--stdin',
                         input=b'\0'.join(paths) + b'\0').split(b'\0')
        if attributes[-1] != b'' or (len(attributes) - 1) % 3:
            raise ScopeError(code, 'Cannot verify Git filter attributes; work retained for inspection.')
        for index in range(0, len(attributes) - 1, 3):
            if attributes[index + 1] == b'filter' and attributes[index + 2] in drivers:
                raise ScopeError(code, 'Writer cannot safely verify configured clean/process filters; use an ordinary source worktree without external filters.')

    def changed_paths(self):
        # No exclude-standard: ignored new files are still changes to inspect.
        raw = git('diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=none',
                  '--name-only', '--no-renames', '-z', self.head, '--')
        raw += git('ls-files', '--others', '-z')
        return {os.fsdecode(name) for name in raw.split(b'\0') if name}

    def __enter__(self):
        self.pointer = self.git_pointer(78)
        root = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).strip()).resolve()
        git_dir = Path(os.fsdecode(git('rev-parse', '--absolute-git-dir')).strip()).resolve()
        common = Path(os.fsdecode(git('rev-parse', '--git-common-dir')).strip()).resolve()
        self.branch = git('branch', '--show-current').strip()
        dedicated = self.branch.startswith(b'codex/') or self.branch.startswith(b'deepseek/')
        if (root != self.root or git_dir == common or
                git('rev-parse', '--show-superproject-working-tree').strip() or
                not dedicated or not (root / '.git').is_file()):
            raise ScopeError(78, 'Writer requires the root of a linked worktree on a dedicated codex/ or deepseek/ branch.')
        for name in self.paths:
            self.validate_path(name)
        self.lock = os.open(git_dir / 'codex-deepseek-writer.lock',
                            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ScopeError(75, 'This worktree already has an active DeepSeek writer.') from None
            self.verify_index_flags(78)
            self.verify_checkout_features(78)
            self.head = git('rev-parse', 'HEAD').strip()
            if self.changed_paths() or git('diff', '--cached', '--no-ext-diff', '--no-textconv',
                    '--ignore-submodules=none', '--name-only', '-z'):
                raise ScopeError(78, 'Writer needs a clean worktree, including untracked and ignored files; existing work is preserved.')
            return self
        except BaseException:
            os.close(self.lock)
            self.lock = None
            raise

    def verify(self):
        if self.git_pointer(73) != self.pointer:
            raise ScopeError(73, 'Writer changed its Git pointer; result rejected, work retained for inspection.')
        self.verify_index_flags(73)
        self.verify_checkout_features(73)
        if (git('rev-parse', 'HEAD').strip() != self.head or
                git('branch', '--show-current').strip() != self.branch or
                git('diff', '--cached', '--no-ext-diff', '--no-textconv',
                    '--ignore-submodules=none', '--name-only', '-z')):
            raise ScopeError(73, 'Writer changed Git state; result rejected, work retained for coordinator inspection.')
        if not self.changed_paths() <= self.paths:
            raise ScopeError(73, 'Writer changed files outside its allowlist; result rejected, work retained for coordinator inspection.')
        for name in self.paths:
            self.validate_path(name)

    def __exit__(self, *_):
        if self.lock is not None:
            os.close(self.lock)

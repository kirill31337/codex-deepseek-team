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


def git(*args):
    result = subprocess.run(['git', *args], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    if result.returncode:
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

    def changed_paths(self):
        # No exclude-standard: ignored new files are still changes to inspect.
        raw = git('diff', '--name-only', '--no-renames', '-z', self.head, '--')
        raw += git('ls-files', '--others', '-z')
        return {os.fsdecode(name) for name in raw.split(b'\0') if name}

    def __enter__(self):
        root = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).strip()).resolve()
        git_dir = Path(os.fsdecode(git('rev-parse', '--absolute-git-dir')).strip()).resolve()
        common = Path(os.fsdecode(git('rev-parse', '--git-common-dir')).strip()).resolve()
        self.branch = git('branch', '--show-current').strip()
        if (root != self.root or git_dir == common or
                git('rev-parse', '--show-superproject-working-tree').strip() or
                not self.branch.startswith(b'codex/') or not (root / '.git').is_file()):
            raise ScopeError(78, 'Writer requires the root of a linked worktree on a dedicated codex/ branch.')
        for name in self.paths:
            self.validate_path(name)
        self.lock = os.open(git_dir / 'codex-deepseek-writer.lock',
                            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ScopeError(75, 'This worktree already has an active DeepSeek writer.') from None
            self.head = git('rev-parse', 'HEAD').strip()
            if self.changed_paths() or git('diff', '--cached', '--name-only', '-z'):
                raise ScopeError(78, 'Writer needs a clean worktree, including untracked and ignored files; existing work is preserved.')
            return self
        except BaseException:
            os.close(self.lock)
            self.lock = None
            raise

    def verify(self):
        if (git('rev-parse', 'HEAD').strip() != self.head or
                git('branch', '--show-current').strip() != self.branch or
                git('diff', '--cached', '--name-only', '-z')):
            raise ScopeError(73, 'Writer changed Git state; result rejected, work retained for coordinator inspection.')
        if not self.changed_paths() <= self.paths:
            raise ScopeError(73, 'Writer changed files outside its allowlist; result rejected, work retained for coordinator inspection.')
        for name in self.paths:
            self.validate_path(name)

    def __exit__(self, *_):
        if self.lock is not None:
            os.close(self.lock)

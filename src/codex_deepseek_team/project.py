"""Idempotent managed block for the codex-deepseek-team project guidance.

``attach`` writes delegation guidance into a clearly marked, unique block in the
repository root ``AGENTS.md``. Every byte outside the owned region is preserved
verbatim: the module never normalises line endings, never drops user text and
owns any separator it inserts, so ``attach`` followed by ``detach`` restores the
pre-existing bytes exactly.
"""
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from .config import sync_directory


START_MARKER = b"<!-- codex-deepseek-team:managed-block:start -->"
END_MARKER = b"<!-- codex-deepseek-team:managed-block:end -->"
DATA_FILE = Path(__file__).resolve().parent / "data" / "delegation.md"
DEFAULT_MODE = 0o644


class ProjectError(Exception):
    """Raised for an invalid or ambiguous target; existing content is untouched."""


def _guidance():
    try:
        body = DATA_FILE.read_bytes()
    except OSError as error:
        raise ProjectError("packaged delegation guidance is unavailable") from error
    return body.strip(b"\n")


def _block_bytes(state):
    metadata = b"<!-- codex-deepseek-team:original:" + state + b" -->\n"
    return START_MARKER + b"\n" + metadata + _guidance() + b"\n" + END_MARKER + b"\n"


def _repository_root(root):
    root = Path(root)
    if not root.is_dir():
        raise ProjectError("target must be an existing directory")
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(root), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as error:
        raise ProjectError("cannot run git to verify the repository root") from error
    if result.returncode:
        raise ProjectError("target is not inside a Git repository")
    toplevel = os.fsdecode(result.stdout).strip()
    if not toplevel:
        raise ProjectError("git did not report a repository root")
    if Path(toplevel).resolve() != root.resolve():
        raise ProjectError("target must be the repository root, not a subdirectory")
    return root.resolve()


def _read_agents(target):
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise ProjectError("cannot safely open AGENTS.md; symbolic links are refused") from error
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise ProjectError("AGENTS.md must be an ordinary file")
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read(), stat.S_IMODE(info.st_mode)


def _locate(content):
    starts = content.count(START_MARKER)
    ends = content.count(END_MARKER)
    if not starts and not ends:
        return None
    if starts != 1 or ends != 1:
        raise ProjectError("AGENTS.md has duplicate or unbalanced managed-block markers")
    begin = content.find(START_MARKER)
    finish = content.find(END_MARKER)
    if finish < begin:
        raise ProjectError("AGENTS.md has out-of-order managed-block markers")
    return begin, finish


def _original_state(content, begin):
    header = content[begin + len(START_MARKER):].split(b"\n", 2)
    if len(header) == 3 and header[0] == b"":
        for state in (b"created", b"existing-empty", b"existing-content"):
            if header[1] == b"<!-- codex-deepseek-team:original:" + state + b" -->":
                return state
    raise ProjectError("managed-block ownership metadata is missing or modified")


def _owned_span(content, begin, finish, state):
    end = finish + len(END_MARKER)
    if content[end:end + 1] != b"\n":
        raise ProjectError("managed-block end separator is missing or modified")
    end += 1
    if state == b"existing-content":
        if not begin or content[begin - 1:begin] != b"\n":
            raise ProjectError("managed-block start separator is missing or modified")
        return begin - 1, end
    return begin, end


def _write_atomic(target, original, mode, content):
    descriptor, temporary = tempfile.mkstemp(
        dir=os.fspath(target.parent), prefix=".AGENTS.md.", suffix=".tmp")
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if _read_agents(target)[0] != original:
            raise ProjectError("AGENTS.md changed while it was being updated; retry")
        os.replace(temporary, target)
        temporary = None
        sync_directory(target.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def attach(root):
    """Add or refresh the managed block; return True when the file changed."""
    repository = _repository_root(root)
    target = repository / "AGENTS.md"
    original, mode = _read_agents(target)
    content = original if original is not None else b""
    marks = _locate(content)
    if marks is None:
        state = b"created" if original is None else (b"existing-content" if original else b"existing-empty")
        block = _block_bytes(state)
        updated = content + (b"\n" if content else b"") + block
    else:
        begin, finish = marks
        state = _original_state(content, begin)
        block = _block_bytes(state)
        updated = content[:begin] + block + content[_owned_span(content, begin, finish, state)[1]:]
    if original is not None and updated == original:
        return False
    _write_atomic(target, original, mode if mode is not None else DEFAULT_MODE, updated)
    return True


def detach(root):
    """Remove the managed block; return True when the file changed."""
    repository = _repository_root(root)
    target = repository / "AGENTS.md"
    original, mode = _read_agents(target)
    if original is None:
        return False
    marks = _locate(original)
    if marks is None:
        return False
    begin, finish = marks
    state = _original_state(original, begin)
    start, end = _owned_span(original, begin, finish, state)
    updated = original[:start] + original[end:]
    if updated == original:
        return False
    if not updated and state == b"created":
        if _read_agents(target)[0] != original:
            raise ProjectError("AGENTS.md changed while it was being updated; retry")
        os.unlink(target)
        sync_directory(target.parent)
        return True
    _write_atomic(target, original, mode, updated)
    return True

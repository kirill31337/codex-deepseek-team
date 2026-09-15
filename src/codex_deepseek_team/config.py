"""Reversible provider setup and private credentials; never change primary auth."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import tomllib

from . import worker

BEGIN = b'# >>> codex-deepseek-team provider >>>'
END = b'# <<< codex-deepseek-team provider <<<'
BLOCK = (b'\n\n' + BEGIN + b'\n[model_providers.deepseek]\n' +
         '\n'.join(f'{key} = {json.dumps(value)}' for key, value in worker.PROVIDER.items()).encode() +
         b'\n' + END + b'\n')


class ConfigError(Exception):
    pass


def read_regular(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise ConfigError('Refusing an unsafe or inaccessible configuration file.') from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ConfigError('Expected a regular configuration file.')
    with os.fdopen(fd, 'rb') as source:
        return source.read()


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ConfigError('Credential/backup directory must be owned by you with mode 700, without symlinks.')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, content, previous, mode=0o600):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), mode)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if read_regular(path) != previous:
            raise ConfigError('File changed concurrently; no update was applied.')
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parse_config(raw):
    try:
        return tomllib.loads((raw or b'').decode('utf-8'))
    except (ValueError, UnicodeError):
        raise ConfigError('Codex config.toml is invalid; existing content was preserved.') from None


def write_config(home, raw, updated):
    path = home / 'config.toml'
    mode = stat.S_IMODE(path.stat().st_mode) if raw is not None else 0o600
    if raw is not None:
        backups = home / 'codex-deepseek-team-backups'
        private_directory(backups)
        backup = backups / f'config-{time.time_ns()}.toml'
        atomic_write(backup, raw, None)
    atomic_write(path, updated, raw, mode)


def configure(home):
    home = Path(home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = read_regular(home / 'config.toml')
    parsed = parse_config(raw)
    providers = parsed.get('model_providers', {})
    if not isinstance(providers, dict):
        raise ConfigError('Invalid model_providers section.')
    if 'deepseek' in providers:
        try:
            worker.provider_config(home)
        except worker.WorkerError:
            raise ConfigError('Existing DeepSeek provider conflicts with this package; no settings changed.') from None
        return False
    if raw and (BEGIN in raw or END in raw):
        raise ConfigError('Managed provider markers are inconsistent; no settings changed.')
    updated = (raw or b'') + BLOCK
    parse_config(updated)
    write_config(home, raw, updated)
    return True


def remove_provider(home):
    home = Path(home)
    raw = read_regular(home / 'config.toml')
    if raw is None or (BEGIN not in raw and END not in raw):
        return False
    if raw.count(BEGIN) != 1 or raw.count(END) != 1 or BLOCK not in raw:
        raise ConfigError('Managed provider was edited; refusing to remove user changes.')
    try:
        worker.provider_config(home)
    except worker.WorkerError:
        raise ConfigError('Provider was edited; no settings removed.') from None
    updated = raw.replace(BLOCK, b'', 1)
    parse_config(updated)
    write_config(home, raw, updated)
    return True


def save_key(value):
    value = value.rstrip('\r\n')
    if len(value) > 4096 or not re.fullmatch(r'[!-~]+', value):
        raise ConfigError('Key must be a single nonempty ASCII value without whitespace, up to 4096 characters.')
    directory = Path.home() / '.config/codex-deepseek'
    private_directory(directory)
    path = directory / 'api-key'
    previous = read_regular(path)
    atomic_write(path, value.encode(), previous)


def delete_key():
    directory = Path.home() / '.config/codex-deepseek'
    if not directory.exists():
        return False
    private_directory(directory)
    path = directory / 'api-key'
    if read_regular(path) is None:
        return False
    path.unlink()
    sync_directory(directory)
    return True

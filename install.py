#!/usr/bin/env python3
"""Install this checkout into a dedicated user venv. No root or API key needed."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

OWNER = 'codex-deepseek-team installer v1\n'
COMMAND = 'codex-deepseek-team'
COMMANDS = (COMMAND, 'deepseek-team')


def check_prefix(prefix, marker):
    if prefix.is_symlink() or (prefix.exists() and not prefix.is_dir()):
        raise ValueError('Installation directory belongs to another tool; choose a new --prefix.')
    if not prefix.exists():
        return
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise ValueError('Refusing an unsafe installation ownership marker.')
    contents = marker.read_text() if marker.exists() else ''
    if contents == OWNER:
        return
    if not OWNER.startswith(contents) or set(prefix.iterdir()) - {marker}:
        raise ValueError('Installation directory belongs to another tool; choose a new --prefix.')


def _links(prefix, bin_dir):
    environment = prefix / 'venv'
    return [(bin_dir / command, environment / 'bin' / command) for command in COMMANDS]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local/share/codex-deepseek-team')
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or sys.version_info < (3, 11):
        print('Linux and Python 3.11+ are required.', file=sys.stderr)
        return 78
    prefix = Path(os.path.abspath(args.prefix.expanduser()))
    bin_dir = Path(os.path.abspath(args.bin_dir.expanduser()))
    marker = prefix / '.codex-deepseek-team-install'
    published = []
    try:
        check_prefix(prefix, marker)
        links = _links(prefix, bin_dir)
        for binary, entrypoint in links:
            if binary.exists() or binary.is_symlink():
                if not binary.is_symlink() or binary.resolve() != entrypoint.resolve():
                    raise ValueError(f'Command {binary.name} already exists outside this installation; choose a different --bin-dir.')
        prefix.mkdir(parents=True, exist_ok=True)
        if not marker.exists() or marker.read_text() != OWNER:
            with marker.open('w') as output:
                output.write(OWNER)
                output.flush()
                os.fsync(output.fileno())
        environment = prefix / 'venv'
        if environment.is_symlink():
            raise ValueError('Refusing a symlinked environment.')
        venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(environment / 'bin/python'), '-m', 'pip', 'install', '--upgrade',
                        str(Path(__file__).resolve().parent)], check=True)
        for _binary, entrypoint in links:
            if not entrypoint.is_file():
                raise ValueError(f'Installation did not produce the expected {entrypoint.name} command.')
        bin_dir.mkdir(parents=True, exist_ok=True)
        for binary, entrypoint in links:
            if not binary.is_symlink():
                with tempfile.TemporaryDirectory(prefix='.team-link-', dir=bin_dir) as temporary:
                    link = Path(temporary) / binary.name
                    link.symlink_to(entrypoint)
                    os.link(link, binary, follow_symlinks=False)
                    published.append((binary, entrypoint))
            if binary.resolve() != entrypoint.resolve():
                raise ValueError(f'Command {binary.name} changed concurrently; the other command was preserved.')
        print('Installed commands: ' + ', '.join(str(binary) for binary, _ in links))
        print(f'Next: {bin_dir / "deepseek-team"} setup')
        print(f'Ensure {bin_dir} is in PATH, then run deepseek-team init in a Git repository.')
        return 0
    except ValueError as error:
        for binary, entrypoint in reversed(published):
            try:
                if binary.is_symlink() and binary.resolve() == entrypoint.resolve():
                    binary.unlink()
            except OSError:
                pass
        print(str(error), file=sys.stderr)
    except (OSError, subprocess.CalledProcessError):
        for binary, entrypoint in reversed(published):
            try:
                if binary.is_symlink() and binary.resolve() == entrypoint.resolve():
                    binary.unlink()
            except OSError:
                pass
        print('Installation failed; check Python venv/pip support, network and directory permissions. Rerun after fixing the error.', file=sys.stderr)
    return 78


if __name__ == '__main__':
    raise SystemExit(main())

"""User-facing CLI for setup, project instructions and isolated workers."""
import argparse
import getpass
from pathlib import Path
import sys

from . import __version__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.platform != 'linux':
        print('This release supports Linux with Python 3.11+ and Codex CLI.', file=sys.stderr)
        return 78
    from . import config, doctor, worker
    if argv and argv[0] == 'worker':
        original = sys.argv
        try:
            sys.argv = ['codex-deepseek-team worker', *argv[1:]]
            return worker.main()
        finally:
            sys.argv = original
    if argv and argv[0] == 'doctor':
        return doctor.main(argv[1:])
    parser = argparse.ArgumentParser(prog='codex-deepseek-team', description=__doc__)
    parser.add_argument('--version', action='version', version=f'codex-deepseek-team {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('setup', help='Configure DeepSeek without changing the coordinator model or auth.')
    setup.add_argument('--no-key', action='store_true', help='Only configure the provider; do not prompt for credentials.')
    commands.add_parser('reset', help='Remove only this package\'s unmodified provider block; retain keys and primary auth.')
    for name, help_text in [('init', 'Attach delegation instructions to a Git repository.'),
                            ('detach', 'Remove the managed instructions and preserve user content.')]:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument('path', nargs='?', type=Path, default=Path.cwd())
    auth = commands.add_parser('auth', help='Manage the private user-level DeepSeek credential.')
    auth_commands = auth.add_subparsers(dest='auth_command', required=True)
    setter = auth_commands.add_parser('set', help='Read the key from a hidden terminal prompt.')
    setter.add_argument('--stdin', action='store_true', help='Read from a pipe; never pass a key as a command argument.')
    auth_commands.add_parser('status', help='Report whether a usable key is present, without displaying it.')
    auth_commands.add_parser('remove', help='Delete the saved key; environment overrides are unaffected.')
    commands.add_parser('doctor', help='Check local setup; add --live for an API test.')
    commands.add_parser('worker', help='Run a worker; use worker --help for read/write options.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'setup':
            changed = config.configure(worker.codex_home())
            print('DeepSeek provider configured.' if changed else 'Compatible DeepSeek provider already configured.')
            if not args.no_key and not worker.load_api_key().strip():
                if sys.stdin.isatty():
                    config.save_key(getpass.getpass('DeepSeek API key (hidden): '))
                    print('Key stored privately.')
                else:
                    print('Set your key with: codex-deepseek-team auth set')
            print('Coordinator model and OpenAI authentication were preserved.')
        elif args.command == 'reset':
            changed = config.remove_provider(worker.codex_home())
            print('Managed provider removed.' if changed else 'No package-owned provider block to remove.')
        elif args.command in ['init', 'detach']:
            from . import project
            try:
                changed = (project.attach if args.command == 'init' else project.detach)(args.path)
            except project.ProjectError as error:
                print(str(error), file=sys.stderr)
                return 78
            print('Project instructions updated.' if changed else 'Project instructions already in the requested state.')
        elif args.command == 'auth':
            if args.auth_command == 'set':
                if not args.stdin and not sys.stdin.isatty():
                    raise config.ConfigError('Use a terminal prompt or --stdin; never put the key in command arguments.')
                value = sys.stdin.read(4097) if args.stdin else getpass.getpass('DeepSeek API key (hidden): ')
                config.save_key(value)
                print('Key stored privately; value omitted.')
            elif args.auth_command == 'remove':
                print('Saved key removed.' if config.delete_key() else 'No saved key was present.')
            else:
                present = bool(worker.load_api_key().strip())
                print('Key available; value omitted.' if present else 'No key configured.')
                return 0 if present else 78
        return 0
    except (config.ConfigError, worker.WorkerError) as error:
        print(error.message if isinstance(error, worker.WorkerError) else str(error), file=sys.stderr)
        return error.code if isinstance(error, worker.WorkerError) else 78
    except (OSError, EOFError):
        print('Operation could not complete; check local paths, permissions and terminal input.', file=sys.stderr)
        return 78
    except KeyboardInterrupt:
        print('Cancelled.', file=sys.stderr)
        return 130

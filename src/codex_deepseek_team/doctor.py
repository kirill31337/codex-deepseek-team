"""Generic local diagnostics and optional synthetic DeepSeek smoke test."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('worker', HERE / 'worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def call(task, cwd=None):
    return subprocess.run([sys.executable, str(HERE / 'worker.py')],
                          input=task, text=True, capture_output=True, cwd=cwd)


def repository_fingerprint(root=None):
    """Detect changes even when a file was already dirty; print no file contents."""
    root = Path(root) if root is not None else Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'])
    digest = hashlib.sha256(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain=v1', '-uall']))
    for name in sorted(set(names.split(b'\0')) - {b''}):
        path = root / os.fsdecode(name)
        digest.update(name + b'\0')
        if path.is_symlink():
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
    return digest.digest()


def probe_error(error, elapsed):
    """Classify failures without formatting exceptions, headers or response bodies."""
    cause = getattr(error, 'reason', error)
    category = type(cause).__name__
    if isinstance(error, json.JSONDecodeError):
        category = 'InvalidJSONResponse'
    return f'API probe: FAIL — {category}, elapsed={elapsed:.1f}s; credentials and response body omitted.'


def stream_model(lines):
    """Read only response metadata; never retain tokens/reasoning or await full generation."""
    for line in lines:
        if not line.startswith(b'data:'):
            continue
        event = json.loads(line[5:])
        response = event.get('response', {})
        actual = response.get('model')
        if isinstance(actual, str) and actual:
            return actual
    raise ValueError('Stream did not expose model metadata')


def api_probe():
    """Runs in a separate, bounded process. Never writes credentials or raw responses."""
    if os.environ.get('CODEX_DEEPSEEK_DISABLED') == '1':
        print('API probe: DISABLED — remove CODEX_DEEPSEEK_DISABLED to run live tests.')
        return 69
    key = worker.load_api_key()
    if not key.strip():
        print('API probe: BLOCKED — DEEPSEEK_API_KEY and saved credential are absent or empty.')
        return 78
    started = time.monotonic()
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        print('API probe: checking /models (socket timeout 20s)...', flush=True)
        request = urllib.request.Request('https://api.deepseek.com/models', headers=headers)
        with opener.open(request, timeout=20) as response:
            models = [item.get('id') for item in json.load(response).get('data', [])]
        available = [model for model in models if isinstance(model, str) and re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', model)]
        if worker.MODEL not in available:
            print('API probe: requested model is absent from /models; available IDs: ' + worker.redact(', '.join(available), key))
            return 78
        print('API probe: requested model is listed; opening Responses stream...', flush=True)
        request = urllib.request.Request('https://api.deepseek.com/responses',
            data=json.dumps({'model': worker.MODEL, 'input': 'Return exactly DEEPSEEK_WORKER_OK.',
                             'reasoning': {'effort': 'none'},
                             'stream': True, 'store': False, 'max_output_tokens': 1024}).encode(), headers=headers)
        with opener.open(request, timeout=60) as response:
            actual_model = stream_model(response)
        if actual_model != worker.MODEL:
            print('API probe: returned model metadata differs from the requested model.')
            return 78
        print('API probe model metadata:', worker.redact(actual_model, key), flush=True)
        return 0
    except urllib.error.HTTPError as error:
        print(f'API probe: FAIL — HTTP {error.code}; response body omitted to protect credentials.')
        return 1
    except (OSError, ValueError) as error:
        print(probe_error(error, time.monotonic() - started))
        return 1


def live_tests():
    if os.environ.get('CODEX_DEEPSEEK_DISABLED') == '1':
        print('Live check disabled by CODEX_DEEPSEEK_DISABLED.')
        return 69
    key = worker.load_api_key()
    if not key.strip():
        print('Live check blocked: set a DeepSeek key with codex-deepseek-team auth set.')
        return 78
    code, out, err = worker.execute(
        [sys.executable, str(Path(__file__).resolve()), '--api-probe'],
        worker.child_environment(worker.codex_home(), key), '', 120)
    if out.strip():
        print(worker.redact(out.strip(), key))
    if code:
        print('API probe failed; no worker started.')
        return code
    state = Path.home() / '.local/state/codex-deepseek'
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='doctor-', dir=state) as directory:
        root = Path(directory)
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        (root / 'evidence.txt').write_text('DEEPSEEK_TEAM_SYNTHETIC_EVIDENCE')
        before = repository_fingerprint(root)
        print('Running one read-only worker on synthetic data; no total deadline...', flush=True)
        result = call('Read only evidence.txt. Return its exact content and DEEPSEEK_TEAM_OK. Do not read other files, run tests, use network or write anything.', cwd=root)
        ok = (result.returncode == 0 and 'DEEPSEEK_TEAM_SYNTHETIC_EVIDENCE' in result.stdout
              and 'DEEPSEEK_TEAM_OK' in result.stdout and before == repository_fingerprint(root))
        print('Synthetic worker check: ' + ('PASS' if ok else 'FAIL'))
        if not ok:
            print('Worker failed or returned incomplete evidence; raw output omitted.')
        return 0 if ok else (result.returncode or 70)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--offline', action='store_true', help='Local checks only (default); no network or key reads.')
    group.add_argument('--live', action='store_true', help='Also verify DeepSeek API routing and one synthetic worker; API charges apply.')
    args = parser.parse_args(argv)
    try:
        config = worker.provider_config(worker.codex_home())
        version = subprocess.check_output(['codex', '--version'], text=True).strip()
        help_text = subprocess.check_output(['codex', 'exec', '--help'], text=True)
        if not all(flag in help_text for flag in ['--strict-config', '--ephemeral', '--json', '--sandbox', '--ignore-rules']):
            print('Codex CLI lacks required options; update Codex before using workers.')
            return 78
        print(version)
        print('Configured coordinator:', config.get('model', '(Codex default)'), '/', config.get('model_provider', 'openai'))
        print('Local configuration checks: PASS. Verified CLI release: 0.153.4; live routing is checked separately.')
        if not args.live:
            print('No network requests or credential validation performed. Use --live for an API check.')
            return 0
        paths = [worker.codex_home() / 'config.toml', worker.codex_home() / 'auth.json']
        before = [path.read_bytes() if path.exists() else None for path in paths]
        code = live_tests()
        unchanged = before == [path.read_bytes() if path.exists() else None for path in paths]
        print('Primary configuration/auth unchanged:', unchanged)
        return code if unchanged else 1
    except worker.WorkerError as error:
        print(error.message, file=sys.stderr)
        return error.code
    except (OSError, subprocess.SubprocessError):
        print('Diagnostics could not complete; check Codex, Git and local configuration.', file=sys.stderr)
        return 78


if __name__ == '__main__':
    try:
        sys.exit(api_probe() if sys.argv[1:] == ['--api-probe'] else main())
    except worker.WorkerError as error:
        print(error.message, file=sys.stderr)
        sys.exit(error.code)

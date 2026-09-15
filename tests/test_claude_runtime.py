"""DeepSeek worker regressions for the Claude Code harness."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

from codex_deepseek_team import worker


SOURCE = Path(__file__).resolve().parents[1] / 'src/codex_deepseek_team/worker.py'
FAKE = r'''#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys
if '--version' in sys.argv:
    print('claude-code fixture')
    sys.exit(0)
if '--help' in sys.argv:
    print('--bare --print --output-format --no-session-persistence --permission-mode --tools --allowedTools')
    sys.exit(0)
root = pathlib.Path(__file__).parent
prompt = sys.stdin.read()
mode = pathlib.Path(__file__).name.removeprefix('claude-')
record = {
    'args': sys.argv[1:],
    'cwd': os.getcwd(),
    'home': os.environ.get('HOME'),
    'base_url': os.environ.get('ANTHROPIC_BASE_URL'),
    'auth_digest': hashlib.sha256(os.environ.get('ANTHROPIC_AUTH_TOKEN', '').encode()).hexdigest(),
    'parent_api_key': 'ANTHROPIC_API_KEY' in os.environ,
    'parent_oauth': 'CLAUDE_CODE_OAUTH_TOKEN' in os.environ,
    'deepseek_key': 'DEEPSEEK_API_KEY' in os.environ,
}
with (root / 'calls').open('a') as output:
    output.write(json.dumps(record) + '\n')
if mode == 'error':
    print(json.dumps({'type':'result','subtype':'error_during_execution','is_error':True,
                      'result':'429 Too Many Requests'}))
else:
    print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':prompt,
                      'session_id':'synthetic','total_cost_usd':0.0}))
'''


class ClaudeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.state = self.root / 'state'
        self.key = secrets.token_hex(24)
        self.env = dict(os.environ,
                        HOME=str(self.root / 'parent-home'),
                        CODEX_HOME=str(self.root / 'missing-codex-home'),
                        DEEPSEEK_API_KEY=self.key,
                        ANTHROPIC_API_KEY='parent-anthropic-secret',
                        CLAUDE_CODE_OAUTH_TOKEN='parent-claude-oauth')
        for mode in ['ok', 'error']:
            path = self.root / f'claude-{mode}'
            path.write_text(FAKE)
            path.chmod(0o700)

    def run_worker(self, mode='ok', task='claude task', extra=()):
        return subprocess.run(
            [sys.executable, str(SOURCE), '--runtime', 'claude',
             '--claude', str(self.root / f'claude-{mode}'),
             '--state-dir', str(self.state), *extra],
            input=task, text=True, capture_output=True, env=self.env,
            cwd=self.repo, timeout=15)

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_claude_readonly_is_bare_restricted_and_auth_isolated(self):
        result = self.run_worker(task='inspect only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'inspect only')
        call, = self.calls()
        args = call['args']
        self.assertIn('--bare', args)
        self.assertIn('-p', args)
        self.assertIn('--no-session-persistence', args)
        self.assertEqual(args[args.index('--output-format') + 1], 'json')
        self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
        self.assertEqual(call['base_url'], 'https://api.deepseek.com/anthropic')
        self.assertEqual(call['auth_digest'], hashlib.sha256(self.key.encode()).hexdigest())
        self.assertFalse(call['parent_api_key'])
        self.assertFalse(call['parent_oauth'])
        self.assertFalse(call['deepseek_key'])
        self.assertEqual(call['cwd'], str(self.repo))
        self.assertEqual(Path(call['home']).parent, self.state)
        self.assertFalse(Path(call['home']).exists())
        self.assertNotIn('inspect only', args)

    def test_claude_writer_exposes_only_file_tools(self):
        args = worker.command('claude', ['src/value.py'], runtime='claude')
        tools = args[args.index('--tools') + 1]
        allowed = args[args.index('--allowedTools') + 1]
        self.assertEqual(tools, 'Read,Glob,Grep,Edit,Write')
        self.assertEqual(allowed, tools)
        self.assertNotIn('Bash', tools)
        self.assertNotIn('WebFetch', tools)
        self.assertNotIn('WebSearch', tools)
        self.assertIn('Allowed files:', ' '.join(args))

    def test_claude_runtime_does_not_require_codex_provider_config(self):
        self.assertFalse(Path(self.env['CODEX_HOME']).exists())
        result = self.run_worker(task='independent runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'independent runtime')

    def test_claude_error_result_is_never_published(self):
        result = self.run_worker(mode='error', task='private candidate', extra=('--attempts', '1'))
        self.assertEqual(result.returncode, 70, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('429', result.stderr)
        self.assertNotIn('private candidate', result.stderr)

    def test_claude_result_parser_rejects_malformed_or_incomplete_payloads(self):
        invalid = ['not json', '[]', '{}', '{"is_error":false,"result":42}',
                   '{"is_error":"no","result":"answer"}']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(worker.WorkerError):
                worker.runtime_result('claude', raw)


if __name__ == '__main__':
    unittest.main()

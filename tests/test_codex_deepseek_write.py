"""Synthetic integration tests for the opt-in DeepSeek worktree writer."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_codex_deepseek_worker as base


MUTATION = '''
if mode == "write":
    task = json.loads(prompt)
    for name, content in task.get("files", {}).items():
        path = pathlib.Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            path.unlink()
        else:
            path.write_text(content)
    if task.get("stage"):
        subprocess.run(["git", "add", "--", "value.txt"], check=True)
    if task.get("commit"):
        subprocess.run(["git", "add", "--", "value.txt"], check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "unexpected commit"], check=True)
    if task.get("switch"):
        subprocess.run(["git", "checkout", "-qb", "codex/unexpected"], check=True)
    if task.get("fail"):
        print("429 synthetic failure after write", file=sys.stderr)
        sys.exit(42)
    prompt = "Implementation ready for coordinator review."
'''


class WriteTests(unittest.TestCase):
    run_worker = base.WorkerTests.run_worker
    calls = base.WorkerTests.calls

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
             *args], cwd=cwd or self.repo, stderr=subprocess.PIPE, text=True).strip()

    def setUp(self):
        base.WorkerTests.setUp(self)
        self.main = self.repo
        self.git('init', '-q', '-b', 'main')
        (self.main / 'value.txt').write_text('original')
        (self.main / 'other.txt').write_text('other')
        (self.main / '.gitignore').write_text('.cache/\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture baseline')
        self.repo = self.root / 'worktree'
        self.git('worktree', 'add', '-q', '-b', 'codex/deepseek/fixture', str(self.repo), cwd=self.main)
        fake = self.root / 'codex-write'
        fake.write_text(base.FAKE.replace('prompt = sys.stdin.read()', 'prompt = sys.stdin.read()\n' + MUTATION))
        fake.chmod(0o700)

    def write(self, files=None, extra_args=(), **task):
        return self.run_worker(task=json.dumps(dict(files=files or {}, **task)), mode='write',
                               args=['--write', '--allow-write', 'value.txt', *extra_args])

    def assert_main_untouched(self):
        self.assertEqual((self.main / 'value.txt').read_text(), 'original')
        self.assertEqual((self.main / 'other.txt').read_text(), 'other')
        self.assertEqual(self.git('status', '--porcelain', cwd=self.main), '')

    def test_writer_changes_only_its_worktree_and_uses_write_sandbox(self):
        r = self.write({'value.txt': 'implemented', 'new/test.txt': 'test'},
                       extra_args=['--allow-write', 'new/test.txt'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.repo / 'value.txt').read_text(), 'implemented')
        self.assertEqual((self.repo / 'new/test.txt').read_text(), 'test')
        self.assertIn('workspace-write', self.calls()[0]['args'])
        self.assertIn('Implementation ready', r.stdout)
        self.assert_main_untouched()

    def test_main_checkout_and_detached_worktree_are_rejected_before_inference(self):
        worktree = self.repo
        self.repo = self.main
        self.assertNotEqual(self.write().returncode, 0)
        self.repo = worktree
        self.git('checkout', '--detach', '-q')
        self.assertNotEqual(self.write().returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assert_main_untouched()

    def test_dirty_initial_worktree_including_ignored_files_is_rejected(self):
        for name in ['value.txt', 'untracked.txt', '.cache/data']:
            with self.subTest(name=name):
                path = self.repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('existing work')
                self.assertNotEqual(self.write().returncode, 0)
                self.assertEqual(path.read_text(), 'existing work')
                if name == 'value.txt':
                    path.write_text('original')
                else:
                    path.unlink()
        self.assertEqual(self.calls(), [])

    def test_write_requires_explicit_safe_file_paths(self):
        invalid = ['/tmp/outside', '../outside', '.git/config', '.env',
                   'secrets/key.txt', 'signing/release.p12', 'keys/id_rsa',
                   'auth.json', 'dir/../value.txt', '.', 'new/*', 'new/']
        for name in invalid:
            with self.subTest(name=name):
                r = self.write(extra_args=['--allow-write', name])
                self.assertNotEqual(r.returncode, 0)
        r = self.run_worker(mode='write', args=['--write'])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_tracked_symlink_cannot_be_an_allowed_write_target(self):
        (self.repo / 'link').symlink_to(self.main, target_is_directory=True)
        self.git('add', 'link')
        self.git('commit', '-qm', 'synthetic symlink')
        r = self.write(extra_args=['--allow-write', 'link/value.txt'])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assert_main_untouched()

    def test_out_of_scope_tracked_untracked_and_ignored_changes_are_rejected(self):
        for name in ['other.txt', 'unexpected.txt', '.cache/result']:
            with self.subTest(name=name):
                r = self.write({name: 'out of scope'})
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout, '')
                path = self.repo / name
                self.assertEqual(path.read_text(), 'out of scope', 'Preserve rejected work for inspection')
                if name == 'other.txt':
                    path.write_text('other')
                else:
                    path.unlink()
        self.assert_main_untouched()

    def test_failed_writer_is_never_retried_and_keeps_partial_work(self):
        r = self.write({'value.txt': 'partial'}, fail=True)
        self.assertEqual(r.returncode, 42, r.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(r.stdout, '')
        self.assertEqual((self.repo / 'value.txt').read_text(), 'partial')
        self.assert_main_untouched()

    def test_writer_rejects_explicit_retries_before_inference(self):
        r = self.write(extra_args=['--attempts', '2'])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_writer_rejects_staging_and_leaves_index_for_inspection(self):
        r = self.write({'value.txt': 'staged'}, stage=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')
        self.assertEqual(self.git('diff', '--cached', '--name-only'), 'value.txt')
        self.assert_main_untouched()

    def test_writer_rejects_commit_and_keeps_it_out_of_main(self):
        r = self.write({'value.txt': 'committed'}, commit=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'unexpected commit')
        self.assert_main_untouched()

    def test_writer_rejects_branch_switch(self):
        r = self.write(switch=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')
        self.assertEqual(self.git('branch', '--show-current'), 'codex/unexpected')
        self.assert_main_untouched()

    def test_writer_can_delete_an_allowed_file(self):
        r = self.write({'value.txt': None})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.repo / 'value.txt').exists())
        self.assert_main_untouched()

    def test_missing_writer_module_preserves_readonly_and_fails_writer_cleanly(self):
        standalone = self.root / 'standalone' / 'worker.py'
        standalone.parent.mkdir()
        shutil.copyfile(base.SOURCE, standalone)
        command = [sys.executable, str(standalone), '--os-sandbox', 'off',
                   '--codex', str(self.root / 'codex-ok'), '--state-dir', str(self.state)]
        r = subprocess.run(command, input='read-only works', text=True, capture_output=True,
                           cwd=self.repo, env=self.env, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'read-only works')
        r = subprocess.run(command + ['--write', '--allow-write', 'value.txt'], input='task',
                           text=True, capture_output=True, cwd=self.repo, env=self.env, timeout=15)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('Traceback', r.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_worktree_lock_prevents_a_second_writer_even_with_another_slot_directory(self):
        git_dir = Path(self.git('rev-parse', '--absolute-git-dir'))
        lock = os.open(git_dir / 'codex-deepseek-writer.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.write(extra_args=['--state-dir', str(self.root / 'other-state')])
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(self.calls(), [])
        finally:
            os.close(lock)
        self.assertEqual(self.write({'value.txt': 'after release'}).returncode, 0)


if __name__ == '__main__':
    unittest.main()

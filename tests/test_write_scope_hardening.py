"""Real-Git regressions for writer admission and result verification."""
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from codex_deepseek_team.write_scope import ScopeError, WriteScope


class WriteScopeHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.main = self.root / 'main'
        self.main.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q', '-b', 'main', cwd=self.main)
        (self.main / 'allowed.py').write_text('value = 1\n')
        (self.main / 'protected.py').write_text('value = 2\n')
        self.git('add', '.', cwd=self.main)
        self.git('commit', '-qm', 'baseline', cwd=self.main)
        self.repo = self.root / 'worktree'
        self.git('worktree', 'add', '-q', '-b', 'codex/hardening',
                 str(self.repo), cwd=self.main)
        self.previous_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.previous_cwd)

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
             *args], cwd=cwd or self.repo, env=self.env, stderr=subprocess.PIPE)

    def assert_rejected(self, operation, code):
        with self.assertRaises(ScopeError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_assume_unchanged_cannot_hide_existing_work(self):
        self.git('update-index', '--assume-unchanged', 'protected.py')
        (self.repo / 'protected.py').write_text('existing private work\n')
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)
        self.assertEqual((self.repo / 'protected.py').read_text(), 'existing private work\n')

    def test_skip_worktree_cannot_hide_existing_work(self):
        self.git('update-index', '--skip-worktree', 'protected.py')
        (self.repo / 'protected.py').write_text('existing private work\n')
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)

    def test_assume_unchanged_cannot_hide_out_of_scope_edits(self):
        with WriteScope(['allowed.py']) as scope:
            self.git('update-index', '--assume-unchanged', 'protected.py')
            (self.repo / 'protected.py').write_text('out of scope\n')
            self.assert_rejected(scope.verify, 73)
        self.assertEqual((self.repo / 'protected.py').read_text(), 'out of scope\n')

    def test_skip_worktree_cannot_hide_out_of_scope_edits(self):
        with WriteScope(['allowed.py']) as scope:
            self.git('update-index', '--skip-worktree', 'protected.py')
            (self.repo / 'protected.py').write_text('out of scope\n')
            self.assert_rejected(scope.verify, 73)

    def test_core_filemode_false_cannot_hide_existing_mode_changes(self):
        self.git('config', 'core.filemode', 'false')
        (self.repo / 'protected.py').chmod(0o755)
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)

    def test_core_filemode_false_cannot_hide_out_of_scope_mode_changes(self):
        self.git('config', 'core.filemode', 'false')
        with WriteScope(['allowed.py']) as scope:
            (self.repo / 'protected.py').chmod(0o755)
            self.assert_rejected(scope.verify, 73)

    def test_repository_fsmonitor_is_not_executed_by_admission_or_verify(self):
        marker = self.root / 'hook-executed'
        hook = self.root / 'fsmonitor'
        hook.write_text(f"#!/bin/sh\n: > '{marker}'\nprintf 'token\\0/\\0'\n")
        hook.chmod(0o700)
        self.git('config', 'core.fsmonitor', str(hook))
        with WriteScope(['allowed.py']) as scope:
            (self.repo / 'allowed.py').write_text('value = 3\n')
            scope.verify()
        self.assertFalse(marker.exists(), 'Verification must not execute repository hooks')

    def test_caller_git_index_override_cannot_hide_staged_changes(self):
        alternate = self.root / 'alternate-index'
        index = Path(os.fsdecode(self.git('rev-parse', '--git-path', 'index')).strip())
        alternate.write_bytes(index.read_bytes())
        (self.repo / 'protected.py').write_text('staged work\n')
        self.git('add', 'protected.py')
        # Matching staged and worktree content remains dirty against HEAD either way;
        # removing the worktree edit leaves a staged-only change to protect.
        (self.repo / 'protected.py').write_text('value = 2\n')
        with mock.patch.dict(os.environ, {'GIT_INDEX_FILE': str(alternate)}):
            with contextlib.ExitStack() as stack:
                self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)

    def test_symlinked_git_pointer_is_rejected(self):
        pointer = self.repo / '.git'
        saved = self.root / 'saved-pointer'
        saved.write_bytes(pointer.read_bytes())
        pointer.unlink()
        pointer.symlink_to(saved)
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)

    def configure_clean_filter(self):
        marker = self.root / 'clean-filter-executed'
        hook = self.root / 'clean-filter'
        hook.write_text(f"#!/bin/sh\n: > '{marker}'\ncat\n")
        hook.chmod(0o700)
        self.git('config', 'filter.demo.clean', str(hook))
        return marker

    def test_clean_filter_is_refused_before_any_unsandboxed_execution(self):
        (self.repo / '.gitattributes').write_text('*.py filter=demo\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-qm', 'attributes')
        marker = self.configure_clean_filter()
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)
        self.assertFalse(marker.exists())

    def test_new_filter_attributes_are_refused_before_result_diff(self):
        marker = self.configure_clean_filter()
        with WriteScope(['allowed.py']) as scope:
            (self.repo / '.gitattributes').write_text('*.py filter=demo\n')
            (self.repo / 'allowed.py').write_text('value = 300\n')
            self.assert_rejected(scope.verify, 73)
        self.assertFalse(marker.exists())
        self.assertTrue((self.repo / '.gitattributes').exists())

    def test_explicitly_unset_filter_remains_supported(self):
        (self.repo / '.gitattributes').write_text('*.py -filter\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-qm', 'attributes')
        marker = self.configure_clean_filter()
        with WriteScope(['allowed.py']) as scope:
            (self.repo / 'allowed.py').write_text('value = 300\n')
            scope.verify()
        self.assertFalse(marker.exists())

    def test_submodule_entries_are_rejected_before_recursive_git_checks(self):
        head = os.fsdecode(self.git('rev-parse', 'HEAD')).strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{head},vendor')
        self.git('commit', '-qm', 'gitlink fixture')
        (self.repo / 'vendor').mkdir()
        with contextlib.ExitStack() as stack:
            self.assert_rejected(lambda: stack.enter_context(WriteScope(['allowed.py'])), 78)

    def test_retargeted_git_pointer_rejects_the_result(self):
        with WriteScope(['allowed.py']) as scope:
            pointer = self.repo / '.git'
            pointer.write_bytes(pointer.read_bytes() + b'\n')
            self.assert_rejected(scope.verify, 73)

    def test_ordinary_allowed_edits_still_pass(self):
        with WriteScope(['allowed.py', 'new/test.py']) as scope:
            (self.repo / 'allowed.py').write_text('value = 3\n')
            (self.repo / 'new').mkdir()
            (self.repo / 'new/test.py').write_text('assert True\n')
            scope.verify()
        self.assertEqual((self.main / 'allowed.py').read_text(), 'value = 1\n')


if __name__ == '__main__':
    unittest.main()

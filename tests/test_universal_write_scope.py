"""Writer worktrees can use a coordinator-neutral deepseek/ branch."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from codex_deepseek_team.write_scope import WriteScope


class UniversalWriteScopeTests(unittest.TestCase):
    def test_deepseek_branch_is_accepted_and_main_checkout_stays_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / 'main'
            main.mkdir()
            subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=main, check=True)
            (main / 'value.py').write_text('value = 1\n')
            subprocess.run(['git', 'add', '.'], cwd=main, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'baseline'], cwd=main, check=True)
            worktree = root / 'worktree'
            subprocess.run(['git', 'worktree', 'add', '-q', '-b', 'deepseek/fixture',
                            str(worktree), 'HEAD'], cwd=main, check=True)
            previous = Path.cwd()
            try:
                os.chdir(worktree)
                with WriteScope(['value.py']) as scope:
                    (worktree / 'value.py').write_text('value = 2\n')
                    scope.verify()
            finally:
                os.chdir(previous)
            self.assertEqual((main / 'value.py').read_text(), 'value = 1\n')


if __name__ == '__main__':
    unittest.main()

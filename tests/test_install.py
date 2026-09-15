"""Installer ownership tests using mocked environments."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('team_installer', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.prefix = root / 'package'
        self.bin = root / 'bin'
        self.args = ['--prefix', str(self.prefix), '--bin-dir', str(self.bin)]

    def simulate_venv(self, path):
        (path / 'bin').mkdir(parents=True, exist_ok=True)
        (path / 'bin/codex-deepseek-team').write_text('entrypoint')

    def test_install_and_repeat_own_only_the_dedicated_entrypoint(self):
        with mock.patch.object(installer.venv.EnvBuilder, 'create', side_effect=self.simulate_venv), \
                mock.patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.main(self.args), 0)
            self.assertEqual(installer.main(self.args), 0)
        command = self.bin / 'codex-deepseek-team'
        self.assertTrue(command.is_symlink())
        self.assertEqual(command.resolve(), self.prefix / 'venv/bin/codex-deepseek-team')
        self.assertEqual({p.name for p in self.bin.iterdir()}, {'codex-deepseek-team'})
        self.assertEqual(run.call_count, 2)

    def test_foreign_prefix_is_never_modified(self):
        self.prefix.mkdir()
        marker = self.prefix / 'unrelated'
        marker.write_bytes(b'keep')
        with mock.patch.object(installer.venv.EnvBuilder, 'create') as create:
            self.assertEqual(installer.main(self.args), 78)
            create.assert_not_called()
        self.assertEqual(list(self.prefix.iterdir()), [marker])

    def test_foreign_entrypoint_is_never_overwritten(self):
        self.bin.mkdir()
        command = self.bin / 'codex-deepseek-team'
        command.write_bytes(b'user program')
        self.assertEqual(installer.main(self.args), 78)
        self.assertEqual(command.read_bytes(), b'user program')
        self.assertFalse(self.prefix.exists())

    def test_symlink_prefix_is_refused(self):
        other = self.prefix.parent / 'other'
        other.mkdir()
        self.prefix.symlink_to(other, target_is_directory=True)
        self.assertEqual(installer.main(self.args), 78)
        self.assertEqual(list(other.iterdir()), [])

    def test_failed_pip_does_not_publish_entrypoint(self):
        with mock.patch.object(installer.venv.EnvBuilder, 'create', side_effect=self.simulate_venv), \
                mock.patch.object(installer.subprocess, 'run', side_effect=installer.subprocess.CalledProcessError(1, 'pip')):
            self.assertEqual(installer.main(self.args), 78)
        self.assertFalse((self.bin / 'codex-deepseek-team').exists())

    def test_recovery_from_interrupted_ownership_marker(self):
        self.prefix.mkdir()
        marker = self.prefix / '.codex-deepseek-team-install'
        for partial in [None, '', installer.OWNER[:8]]:
            with self.subTest(partial=partial):
                if partial is not None:
                    marker.write_text(partial)
                with mock.patch.object(installer.venv.EnvBuilder, 'create', side_effect=self.simulate_venv), \
                        mock.patch.object(installer.subprocess, 'run'):
                    self.assertEqual(installer.main(self.args), 0)
                self.assertEqual(marker.read_text(), installer.OWNER)
                import shutil
                shutil.rmtree(self.prefix / 'venv')

    def test_equivalent_prefix_and_relative_command_link_allow_update(self):
        with mock.patch.object(installer.venv.EnvBuilder, 'create', side_effect=self.simulate_venv), \
                mock.patch.object(installer.subprocess, 'run'):
            self.assertEqual(installer.main(self.args), 0)
            command = self.bin / 'codex-deepseek-team'
            command.unlink()
            command.symlink_to('../package/venv/bin/codex-deepseek-team')
            args = ['--prefix', str(self.prefix / '../package'), '--bin-dir', str(self.bin)]
            self.assertEqual(installer.main(args), 0)

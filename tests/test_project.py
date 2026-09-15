"""Synthetic Git-repository tests for the managed AGENTS.md block."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from codex_deepseek_team import project


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="codex-project-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", os.fspath(self.repo)],
                       check=True, stderr=subprocess.DEVNULL)
        self.agents = self.repo / "AGENTS.md"

    def write(self, data, mode=None):
        self.agents.write_bytes(data)
        if mode is not None:
            os.chmod(self.agents, mode)

    def test_attach_creates_file_then_detach_restores_absence(self):
        self.assertFalse(self.agents.exists())
        self.assertTrue(project.attach(self.repo))
        data = self.agents.read_bytes()
        self.assertIn(project.START_MARKER, data)
        self.assertIn(project.END_MARKER, data)
        self.assertTrue(project.detach(self.repo))
        self.assertFalse(self.agents.exists())

    def test_attach_is_idempotent(self):
        self.write(b"existing guidance\n")
        self.assertTrue(project.attach(self.repo))
        first = self.agents.read_bytes()
        self.assertFalse(project.attach(self.repo))
        self.assertEqual(self.agents.read_bytes(), first)

    def test_preserves_preexisting_empty_file(self):
        self.write(b"", mode=0o640)
        project.attach(self.repo)
        project.detach(self.repo)
        self.assertTrue(self.agents.exists())
        self.assertEqual(self.agents.read_bytes(), b"")
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o640)

    def test_refresh_and_detach_preserve_user_suffix(self):
        original = b"rules without final newline"
        suffix = b"\n# Added after installation\r\ntext\r\n"
        self.write(original)
        project.attach(self.repo)
        self.write(self.agents.read_bytes() + suffix)
        with mock.patch.object(project, "_guidance", return_value=b"Updated guidance"):
            self.assertTrue(project.attach(self.repo))
            self.assertFalse(project.attach(self.repo))
        project.detach(self.repo)
        self.assertEqual(self.agents.read_bytes(), original + suffix)

    def test_balanced_markers_without_ownership_metadata_are_rejected(self):
        original = b"user text\n" + project.START_MARKER + b"\nbody\n" + project.END_MARKER + b"\n"
        self.write(original)
        for operation in (project.attach, project.detach):
            with self.assertRaises(project.ProjectError):
                operation(self.repo)
            self.assertEqual(self.agents.read_bytes(), original)

    def test_attach_detach_preserves_bytes_without_final_newline(self):
        original = b"# Hand written rules\nno trailing newline here"
        self.write(original)
        self.assertTrue(project.attach(self.repo))
        self.assertTrue(project.detach(self.repo))
        self.assertEqual(self.agents.read_bytes(), original)

    def test_attach_detach_preserves_crlf_bytes(self):
        original = b"line one\r\nline two\r\n"
        self.write(original)
        self.assertTrue(project.attach(self.repo))
        self.assertTrue(project.detach(self.repo))
        self.assertEqual(self.agents.read_bytes(), original)

    def test_attach_detach_preserves_trailing_newline(self):
        original = b"# Rules\n\nsome text\n"
        self.write(original)
        self.assertTrue(project.attach(self.repo))
        self.assertTrue(project.detach(self.repo))
        self.assertEqual(self.agents.read_bytes(), original)

    def test_attach_refreshes_changed_block(self):
        self.write(b"# Rules\n")
        self.assertTrue(project.attach(self.repo))
        content = self.agents.read_bytes()
        begin = content.index(project.START_MARKER)
        end = content.index(project.END_MARKER) + len(project.END_MARKER)
        mutated = content[:begin] + content[begin:end].replace(b"coordinator", b"leads") + content[end:]
        self.write(mutated)
        self.assertTrue(project.attach(self.repo))
        self.assertIn(project.START_MARKER, self.agents.read_bytes())

    def test_detach_on_missing_returns_false(self):
        self.assertFalse(project.detach(self.repo))

    def test_detach_without_block_returns_false(self):
        self.write(b"just user text\n")
        self.assertFalse(project.detach(self.repo))
        self.assertEqual(self.agents.read_bytes(), b"just user text\n")

    def test_rejects_unbalanced_markers(self):
        original = project.START_MARKER + b"\nbogus\n"
        self.write(original)
        with self.assertRaises(project.ProjectError):
            project.attach(self.repo)
        self.assertEqual(self.agents.read_bytes(), original)

    def test_rejects_duplicate_markers(self):
        original = (project.START_MARKER + b"\na\n" + project.END_MARKER + b"\n" +
                    project.START_MARKER + b"\nb\n" + project.END_MARKER + b"\n")
        self.write(original)
        with self.assertRaises(project.ProjectError):
            project.detach(self.repo)
        self.assertEqual(self.agents.read_bytes(), original)

    def test_rejects_out_of_order_markers(self):
        original = project.END_MARKER + b"\nbody\n" + project.START_MARKER + b"\n"
        self.write(original)
        with self.assertRaises(project.ProjectError):
            project.attach(self.repo)
        self.assertEqual(self.agents.read_bytes(), original)

    def test_rejects_symlinked_agents(self):
        outside = self.tmp / "outside.md"
        outside.write_bytes(b"outside\n")
        os.symlink(outside, self.agents)
        with self.assertRaises(project.ProjectError):
            project.attach(self.repo)
        self.assertEqual(outside.read_bytes(), b"outside\n")

    def test_rejects_non_file_agents(self):
        self.agents.mkdir()
        with self.assertRaises(project.ProjectError):
            project.attach(self.repo)
        self.assertTrue(self.agents.is_dir())

    def test_preserves_existing_mode(self):
        self.write(b"# Rules\n", mode=0o640)
        self.assertTrue(project.attach(self.repo))
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o640)
        self.assertTrue(project.detach(self.repo))
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o640)

    def test_new_file_uses_default_mode(self):
        self.assertTrue(project.attach(self.repo))
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o644)

    def test_rejects_non_repository(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(project.ProjectError):
            project.attach(plain)

    def test_rejects_subdirectory(self):
        nested = self.repo / "nested"
        nested.mkdir()
        with self.assertRaises(project.ProjectError):
            project.attach(nested)

    def test_rejects_missing_directory(self):
        with self.assertRaises(project.ProjectError):
            project.attach(self.tmp / "absent")

    def test_does_not_overwrite_concurrent_change(self):
        self.write(b"# Rules\n")
        original_read = project._read_agents
        seen = []

        def racing(target):
            seen.append(target)
            if len(seen) > 1:
                return b"changed concurrently", 0o644
            return original_read(target)

        with mock.patch.object(project, "_read_agents", racing):
            with self.assertRaises(project.ProjectError):
                project.attach(self.repo)
        self.assertEqual(self.agents.read_bytes(), b"# Rules\n")
        self.assertEqual({p.name for p in self.repo.iterdir()}, {"AGENTS.md", ".git"})


if __name__ == "__main__":
    unittest.main()

"""Fail-closed handling of malformed output and unsafe local runtime state."""
import json
import os
import unittest

import test_codex_deepseek_worker as base


class EventIntegrityTests(unittest.TestCase):
    def completed(self):
        return '\n'.join(json.dumps(event) for event in (
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'answer'}},
            {'type': 'turn.completed'}))

    def test_malformed_json_cannot_be_hidden_by_a_completed_answer(self):
        for raw in ('not-json\n' + self.completed(),
                    self.completed() + '\n{"type":"turn.failed",',
                    self.completed() + '\n[untrusted data'):
            with self.subTest(raw=raw):
                with self.assertRaises(base.worker.WorkerError) as caught:
                    base.worker.result_events(raw)
                self.assertEqual(caught.exception.code, 70)

    def test_event_type_must_be_a_nonempty_string(self):
        for value in (None, '', 42, [], {}):
            with self.subTest(value=value), self.assertRaises(base.worker.WorkerError):
                base.worker.result_events(json.dumps({'type': value}) + '\n' + self.completed())

    def test_blank_lines_and_future_named_events_remain_compatible(self):
        result = base.worker.result_events(
            '\n  \n{"type":"future.metadata","data":42}\n' + self.completed() + '\n')
        self.assertEqual(result, ('answer', '', True))


class RuntimeHardeningTests(unittest.TestCase):
    setUp = base.WorkerTests.setUp
    run_worker = base.WorkerTests.run_worker
    calls = base.WorkerTests.calls

    def test_invalid_environment_key_stops_before_inference_without_leaking(self):
        for value in ('not a key', 'line1\nline2', 'synthetic-ключ', 'x' * 5000):
            with self.subTest(value_length=len(value)):
                result = self.run_worker(env={'DEEPSEEK_API_KEY': value})
                self.assertEqual(result.returncode, 78, result.stderr)
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_invalid_utf8_is_a_clean_failure_not_a_traceback(self):
        fake = self.root / 'codex-invalid-utf8'
        fake.write_text(base.FAKE.replace(
            'prompt = sys.stdin.read()',
            'prompt = sys.stdin.read()\nos.write(1, b"\\xff")\nsys.exit(0)'))
        fake.chmod(0o700)
        result = self.run_worker(mode='invalid-utf8')
        self.assertEqual(result.returncode, 70, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(list(self.state.glob('session-*')))

    def test_state_directory_must_be_private_without_chmodding_user_data(self):
        self.state.mkdir(mode=0o755)
        result = self.run_worker()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.calls(), [])

    def test_symlinked_state_directory_is_rejected(self):
        target = self.root / 'other-state'
        target.mkdir(mode=0o700)
        self.state.symlink_to(target, target_is_directory=True)
        result = self.run_worker()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(target.iterdir()), [])

    def test_nonregular_lock_is_rejected_before_inference(self):
        self.state.mkdir(mode=0o700)
        os.mkfifo(self.state / 'worker-0.lock', 0o600)
        result = self.run_worker()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_hardlinked_lock_is_rejected_without_touching_its_target(self):
        self.state.mkdir(mode=0o700)
        target = self.root / 'existing-data'
        target.write_text('preserve this')
        target.chmod(0o600)
        os.link(target, self.state / 'worker-0.lock')
        result = self.run_worker()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(target.read_text(), 'preserve this')
        self.assertEqual(self.calls(), [])

    def test_public_lock_is_rejected_without_changing_permissions(self):
        self.state.mkdir(mode=0o700)
        lock = self.state / 'worker-0.lock'
        lock.write_text('')
        lock.chmod(0o644)
        result = self.run_worker()
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()

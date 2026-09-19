"""Host protocol fault injection; these tests do not claim kernel isolation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from entrotter_engine.artifact import seal
from entrotter_engine.evm import ExecutionError
from entrotter_engine.isolated import run_isolated, worker_args, verify_daemon
from entrotter_engine.runner import run

IMAGE = 'sha256:' + 'a' * 64


class IsolatedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenario = json.loads((Path(__file__).parent / 'data/fixture.json').read_text())
        self.report = run(self.scenario)
        self.script = self.root / 'client.py'
        self.script.write_text('''import os,sys,time
from pathlib import Path
if sys.argv[1]=='ps': sys.exit(0)
if sys.argv[1]=='rm':
    Path(os.environ['FAKE_CLEANUP']).write_text(sys.argv[-1]);sys.exit(0)
sys.stdin.buffer.read()
if os.environ.get('FAKE_HANG'): time.sleep(10)
sys.stdout.write(os.environ['FAKE_RESPONSE']);sys.stdout.flush()
''')
        @contextmanager
        def fake_client():
            yield [sys.executable, str(self.script)]
        self.addCleanup(patch.stopall)
        patch('entrotter_engine.isolated.client', fake_client).start()
        self.daemon_check = patch('entrotter_engine.isolated.verify_daemon', return_value={}).start()
        patch.dict(os.environ, {'ENTROTTER_WORKER_IMAGE': IMAGE,
                               'FAKE_RESPONSE': json.dumps(self.report),
                               'FAKE_CLEANUP': str(self.root / 'cleanup')}).start()

    def assert_cleanup(self):
        self.assertRegex((self.root / 'cleanup').read_text(), '^entrotter-run-[a-f0-9]{32}$')

    def test_valid_response_matches_and_removes_owned_container(self):
        self.assertEqual(run_isolated(self.scenario), self.report)
        self.assert_cleanup()

    def test_invalid_or_wrong_scenario_response_fails_closed(self):
        changed = dict(self.report)
        changed['scenario'] = {'different': True}
        for response in ['secret provider error', '[]', json.dumps(seal(changed))]:
            with self.subTest(response=response), patch.dict(os.environ, {'FAKE_RESPONSE': response}):
                with self.assertRaises(ExecutionError) as caught:
                    run_isolated(self.scenario)
                self.assertNotIn('secret', str(caught.exception))
                self.assert_cleanup()

    def test_output_budget_stops_reader_and_cleans_up(self):
        with patch('entrotter_engine.isolated.MAX_OUTPUT', 16):
            with self.assertRaisesRegex(ExecutionError, '8 MiB'):
                run_isolated(self.scenario)
        self.assert_cleanup()

    def test_timeout_terminates_client_and_requests_container_removal(self):
        with patch.dict(os.environ, {'FAKE_HANG': '1'}), patch('entrotter_engine.isolated.HOST_TIMEOUT', .15):
            with self.assertRaisesRegex(ExecutionError, 'timed out'):
                run_isolated(self.scenario)
        self.assert_cleanup()

    def test_cleanup_failure_is_explicit(self):
        with patch('entrotter_engine.isolated.subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 10)):
            with self.assertRaisesRegex(ExecutionError, 'cleanup could not be confirmed'):
                run_isolated(self.scenario)

    def test_input_budget_is_checked_before_launch(self):
        with patch('entrotter_engine.isolated.MAX_INPUT', 1):
            with self.assertRaisesRegex(ExecutionError, '256 KiB'):
                run_isolated(self.scenario)
        self.assertFalse((self.root / 'cleanup').exists())

    def test_image_must_be_immutable_and_network_is_mode_bound(self):
        for image in ['', 'latest', 'repo:tag', IMAGE + ':tag']:
            with self.assertRaises(ExecutionError):
                worker_args(['docker'], image, 'test')
        normal = worker_args(['docker'], IMAGE, 'test')
        fork = worker_args(['docker'], IMAGE, 'test', fork=True)
        self.assertIn('--network=none', normal)
        self.assertNotIn('ENTROTTER_RPC_URL', normal)
        self.assertIn('--network=bridge', fork)
        self.assertIn('ENTROTTER_RPC_URL', fork)
        self.assertNotIn('--privileged', fork)

    def test_missing_kernel_controls_are_rejected(self):
        healthy = dict(OSType='linux', CgroupVersion='2', MemoryLimit=True,
                       SwapLimit=True, CpuCfsQuota=True, PidsLimit=True)
        for field in healthy:
            wrong = {**healthy, field: False}
            response = subprocess.CompletedProcess([], 0, json.dumps(wrong).encode())
            with self.subTest(field=field), patch('entrotter_engine.isolated.subprocess.run', return_value=response):
                with self.assertRaises(ExecutionError):
                    verify_daemon(['docker'])


if __name__ == '__main__':
    unittest.main()

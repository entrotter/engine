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
from entrotter_engine.isolated import run_isolated, worker_args, verify_daemon, WorkerBusy, _slot, _cleanup
from entrotter_engine.runner import run_native as run

IMAGE = 'sha256:' + 'a' * 64


class IsolatedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenario = json.loads((Path(__file__).parent / 'data/fixture.json').read_text())
        self.report = run(self.scenario)
        self.script = self.root / 'client.py'
        self.script.write_text('''import json,os,sys,time
from pathlib import Path
state=Path(os.environ['FAKE_STATE'])
if sys.argv[1]=='ps':
    if state.exists():
        data=json.loads(state.read_text())
        filters=[x for x in sys.argv if x.startswith('label=org.entrotter.owner=')]
        if not filters or filters==['label=org.entrotter.owner='+data['owner']]: print(data['id'])
    sys.exit(0)
if sys.argv[1]=='rm':
    Path(os.environ['FAKE_CLEANUP']).write_text(sys.argv[-1])
    if state.exists() and json.loads(state.read_text())['id']==sys.argv[-1]: state.unlink()
    sys.exit(0)
owner=next(x.split('=',1)[1] for x in sys.argv if x.startswith('org.entrotter.owner='))
container='b'*64
if os.environ.get('FAKE_CONFLICT'):
    state.write_text(json.dumps({'owner':'winner','id':'c'*64}))
    sys.exit(125)
state.write_text(json.dumps({'owner':owner,'id':container}))
sys.stdin.buffer.read()
if os.environ.get('FAKE_HANG'): time.sleep(10)
sys.stdout.write(os.environ['FAKE_RESPONSE']);sys.stdout.flush()
if os.environ.get('FAKE_FAIL_AFTER_CREATE'): sys.exit(125)
''')
        @contextmanager
        def fake_client():
            yield [sys.executable, str(self.script)]
        self.addCleanup(patch.stopall)
        patch('entrotter_engine.isolated.client', fake_client).start()
        self.daemon_check = patch('entrotter_engine.isolated.verify_daemon', return_value={}).start()
        patch.dict(os.environ, {'ENTROTTER_WORKER_IMAGE': IMAGE,
                               'FAKE_RESPONSE': json.dumps(self.report),
                               'FAKE_STATE': str(self.root / 'state'),
                               'FAKE_CLEANUP': str(self.root / 'cleanup')}).start()

    def assert_cleanup(self):
        self.assertEqual((self.root / 'cleanup').read_text(), 'b' * 64)

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
        with patch('entrotter_engine.isolated._slot', side_effect=[None, ExecutionError('query failed')]):
            with self.assertRaisesRegex(ExecutionError, 'cleanup could not be confirmed'):
                run_isolated(self.scenario)

    def test_busy_preflight_does_not_launch_or_remove_another_owner(self):
        (self.root / 'state').write_text(json.dumps({'owner': 'another', 'id': 'c' * 64}))
        self.assertEqual(_slot([sys.executable, str(self.script)]), 'c' * 64)
        with patch('entrotter_engine.isolated._slot', return_value='c' * 64), \
             patch('entrotter_engine.isolated.subprocess.Popen') as launch:
            with self.assertRaises(WorkerBusy):
                run_isolated(self.scenario)
            launch.assert_not_called()
        self.assertFalse((self.root / 'cleanup').exists())

    def test_admission_query_fails_closed(self):
        for response in [subprocess.CompletedProcess([], 0, b'partial-id'),
                         subprocess.CompletedProcess([], 0, b'c'*64+b'\n'+b'd'*64),
                         subprocess.CompletedProcess([], 0, b'\xff')]:
            with patch('entrotter_engine.isolated.subprocess.run', return_value=response):
                with self.assertRaises(ExecutionError):
                    _slot(['docker'])
        for error in [OSError(), subprocess.TimeoutExpired('docker', 10),
                      subprocess.CalledProcessError(1, 'docker')]:
            with patch('entrotter_engine.isolated.subprocess.run', side_effect=error):
                with self.assertRaises(ExecutionError):
                    _slot(['docker'])

    def test_late_cleanup_removes_immutable_id_not_replacement_name(self):
        with patch('entrotter_engine.isolated._slot', side_effect=['c' * 64, None]), \
             patch('entrotter_engine.isolated.subprocess.run') as remove:
            _cleanup(['docker'], 'old-owner')
        self.assertEqual(remove.call_args.args[0], ['docker', 'rm', '--force', 'c' * 64])

    def test_race_conflict_never_removes_winner(self):
        with patch.dict(os.environ, {'FAKE_CONFLICT': '1'}):
            with self.assertRaises(ExecutionError) as caught:
                run_isolated(self.scenario)
        self.assertNotIsInstance(caught.exception, WorkerBusy)
        self.assertFalse((self.root / 'cleanup').exists())
        self.assertEqual(json.loads((self.root / 'state').read_text())['owner'], 'winner')

    def test_created_worker_failure_is_not_misreported_as_busy(self):
        with patch.dict(os.environ, {'FAKE_FAIL_AFTER_CREATE': '1'}):
            with self.assertRaises(ExecutionError) as caught:
                run_isolated(self.scenario)
        self.assertNotIsInstance(caught.exception, WorkerBusy)
        self.assert_cleanup()

    def test_cleanup_never_removes_a_foreign_owner(self):
        (self.root / 'state').write_text(json.dumps({'owner': 'winner', 'id': 'c' * 64}))
        _cleanup([sys.executable, str(self.script)], 'loser')
        self.assertFalse((self.root / 'cleanup').exists())
        self.assertTrue((self.root / 'state').exists())

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

"""Real daemon admission tests; detached idle workers occupy actual capacity."""
from contextlib import contextmanager
import http.client
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from entrotter_engine.api import EngineServer
from entrotter_engine.isolated import client, worker_args
from entrotter_engine.runner import run, run_native

ROOT = Path(__file__).resolve().parents[1]
SLOT = 'entrotter-active-worker'


@contextmanager
def occupied_slot(*, start=True):
    with client() as prefix:
        args = worker_args(prefix, os.environ['ENTROTTER_WORKER_IMAGE'], SLOT)
        if start:
            args.insert(-1, '--detach')
        else:
            args[len(prefix)] = 'create'
        # Docker owns the atomic name. Never delete by this shared name.
        container = subprocess.check_output(args, stdin=subprocess.DEVNULL, text=True, timeout=10).strip()
        try:
            yield prefix, container
        finally:
            subprocess.run([*prefix, 'rm', '--force', container], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def delayed_args(original, *args, **kwargs):
    values = original(*args, **kwargs)
    # Timing-only fault injection: real Docker flags and the real worker run.
    return [*values[:-1], '--entrypoint=python', values[-1], '-c',
            'import time; time.sleep(5); from entrotter_engine._isolated_worker import main; raise SystemExit(main())']


def race_contender(barrier, outcomes, scenario):
    from entrotter_engine import isolated
    original_slot = isolated._slot
    original_args = isolated.worker_args
    first = True

    def synchronized_slot(prefix, owner=None):
        nonlocal first
        result = original_slot(prefix, owner)
        if owner is None and first:
            first = False
            if result is not None:
                raise AssertionError('Race setup requires an empty daemon slot')
            barrier.wait(timeout=20)
        return result

    try:
        with patch.object(isolated, '_slot', synchronized_slot), \
             patch.object(isolated, 'worker_args', lambda *a, **kw: delayed_args(original_args, *a, **kw)):
            outcomes.put(('success', run(scenario)))
    except isolated.ExecutionError as error:
        outcomes.put(('rejected', str(error)))
    except BaseException as error:
        outcomes.put(('unexpected', type(error).__name__ + ': ' + str(error)))


class DaemonAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / 'tests/data/fixture.json').read_text())

    def assert_incumbent(self, prefix, container):
        current = subprocess.check_output(
            [*prefix, 'inspect', '--format', '{{.Id}} {{.State.Running}}', SLOT],
            text=True, timeout=10).strip()
        self.assertEqual(current, container + ' true')

    def test_two_processes_race_after_both_observe_empty_slot(self):
        context = multiprocessing.get_context('spawn')
        barrier = context.Barrier(2)
        outcomes = context.Queue()
        processes = [context.Process(target=race_contender, args=(barrier, outcomes, self.scenario))
                     for _ in range(2)]
        try:
            for process in processes:
                process.start()
            results = [outcomes.get(timeout=40) for _ in processes]
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(sorted(item[0] for item in results), ['rejected', 'success'], [(kind, payload if kind != 'success' else payload['artifact_id']) for kind, payload in results])
            report = next(item[1] for item in results if item[0] == 'success')
            self.assertEqual(report, run_native(self.scenario))
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            outcomes.close()
            outcomes.join_thread()
        self.assertEqual(run(self.scenario), run_native(self.scenario))

    def test_unstarted_container_keeps_slot_until_explicit_owned_removal(self):
        from entrotter_engine.isolated import WorkerBusy
        with occupied_slot(start=False) as (prefix, container):
            with self.assertRaises(WorkerBusy):
                run(self.scenario)
            state = subprocess.check_output(
                [*prefix, 'inspect', '--format', '{{.Id}} {{.State.Status}}', SLOT],
                text=True, timeout=10).strip()
            self.assertEqual(state, container + ' created')
        self.assertEqual(run(self.scenario), run_native(self.scenario))

    def test_host_timeout_releases_owned_slot_for_next_run(self):
        from entrotter_engine import isolated
        original_args = isolated.worker_args
        with patch.object(isolated, 'worker_args', lambda *a, **kw: delayed_args(original_args, *a, **kw)), \
             patch.object(isolated, 'HOST_TIMEOUT', 2):
            with self.assertRaisesRegex(isolated.ExecutionError, 'timed out'):
                run(self.scenario)
        with client() as prefix:
            self.assertIsNone(isolated._slot(prefix))
        self.assertEqual(run(self.scenario), run_native(self.scenario))

    def test_cli_rejects_occupied_daemon_without_replacing_export(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            output.write_text('keep prior export')
            with occupied_slot() as (prefix, container):
                result = subprocess.run(
                    [sys.executable, '-m', 'entrotter_engine', 'run',
                     str(ROOT / 'tests/data/fixture.json'), '-o', str(output)],
                    capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, 'Independent CLI bypassed occupied worker slot')
                self.assertIn('busy', result.stderr.lower())
                self.assertEqual(output.read_text(), 'keep prior export')
                self.assert_incumbent(prefix, container)
        self.assertEqual(run(self.scenario), run_native(self.scenario))

    def test_api_rejects_occupied_daemon_without_storing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            server = EngineServer(0, output=Path(directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            try:
                with occupied_slot() as (prefix, container):
                    connection.request('POST', '/v1/runs', json.dumps(self.scenario),
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    body = json.loads(response.read())
                    self.assertEqual(response.status, 429, 'Independent API bypassed occupied worker slot')
                    self.assertEqual(body, {'error': 'worker_busy_retry_later'})
                    self.assertEqual(list(Path(directory).glob('*.json')), [])
                    self.assert_incumbent(prefix, container)
                connection.request('POST', '/v1/runs', json.dumps(self.scenario),
                                   {'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read()), run_native(self.scenario))
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()

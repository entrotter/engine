"""Real entrypoint regressions; no daemon is needed for fail-closed checks."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from entrotter_engine.api import EngineServer
from entrotter_engine.evm import ExecutionError
from entrotter_engine.runner import run

ROOT = Path(__file__).resolve().parents[1]


class DefaultExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenario = json.loads((ROOT / 'tests/data/fixture.json').read_text())
        self.missing = {'ENTROTTER_DOCKER_SOCKET': str(self.root / 'missing.sock'),
                        'ENTROTTER_WORKER_IMAGE': ''}

    def test_public_runner_never_falls_back_when_worker_is_unavailable(self):
        with patch.dict(os.environ, self.missing):
            with self.assertRaises(ExecutionError):
                run(self.scenario)

    def test_cli_default_rejects_missing_worker_without_replacing_export(self):
        target = self.root / 'report.json'
        target.write_bytes(b'previous report')
        result = subprocess.run([sys.executable, '-m', 'entrotter_engine', 'run',
                                 str(ROOT / 'tests/data/fixture.json'), '-o', str(target)],
                                env={**os.environ, **self.missing}, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(target.read_bytes(), b'previous report')

    def test_api_default_rejects_missing_worker_without_saving_report(self):
        with patch.dict(os.environ, self.missing):
            server = EngineServer(0, output=self.root / 'reports')
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                connection.request('POST', '/v1/runs', json.dumps(self.scenario),
                                   {'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual(response.status, 422, response.read())
                self.assertEqual(list((self.root / 'reports').glob('*.json')), [])
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join()

    def test_native_requires_explicit_opt_in_and_preserves_fixture_result(self):
        target = self.root / 'native.json'
        result = subprocess.run([sys.executable, '-m', 'entrotter_engine', 'run',
                                 str(ROOT / 'tests/data/fixture.json'), '--native', '-o', str(target)],
                                env={**os.environ, **self.missing}, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(target.read_text())['artifact_id'],
                         'e6a12db320dd37e8d37341fe202836d9442a7e428f89381223c9ab29faa479a6')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO regression')
    def test_scenario_fifo_is_rejected_without_waiting_for_a_writer(self):
        source = self.root / 'scenario.fifo'
        os.mkfifo(source)
        result = subprocess.run([sys.executable, '-m', 'entrotter_engine', 'run',
                                 str(source), '-o', str(self.root / 'result.json')],
                                env={**os.environ, **self.missing}, capture_output=True,
                                text=True, timeout=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn('regular file', result.stderr)


if __name__ == '__main__':
    unittest.main()

"""Real loopback sockets and files; accelerated deadline uses the production path."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from entrotter_engine.api import EngineServer
from entrotter_engine.store import ArtifactStore, MAX_REPORT_BYTES


class ObservedServer(EngineServer):
    def __init__(self, *args, **kwargs):
        self.condition = threading.Condition()
        self.active = 0
        self.peak = 0
        super().__init__(*args, **kwargs)

    def process_request_thread(self, request, address):
        with self.condition:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.condition.notify_all()
        try:
            super().process_request_thread(request, address)
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


class APILimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = ObservedServer(0, output=self.temp.name, isolated=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.scenario = json.loads((Path(__file__).parent / 'data/fixture.json').read_text())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def wait_active(self, count):
        with self.server.condition:
            self.assertTrue(self.server.condition.wait_for(lambda: self.server.active == count, timeout=3))

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_eight_idle_connections_bound_handlers_and_recover(self):
        sockets = []
        try:
            for _ in range(8):
                sockets.append(socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3))
            self.wait_active(8)
            status, report = self.request('GET', '/health')
            self.assertEqual((status, report), (503, {'error': 'connection_limit'}))
            self.assertEqual(self.server.peak, 8)
            sockets.pop().close()
            self.wait_active(7)
            self.assertEqual(self.request('GET', '/health')[0], 200)
            self.assertEqual(self.server.peak, 8)
        finally:
            for connection in sockets:
                connection.close()
            self.wait_active(0)

    def test_absolute_deadline_closes_idle_socket_and_returns_capacity(self):
        with patch('entrotter_engine.api.MAX_CONNECTION_SECONDS', .2):
            connection = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2)
            try:
                self.wait_active(1)
                started = time.monotonic()
                self.assertEqual(connection.recv(1), b'')
                self.assertLess(time.monotonic() - started, 1)
                self.wait_active(0)
            finally:
                connection.close()
        self.assertEqual(self.request('GET', '/health')[0], 200)

    def test_overload_response_survives_post_body_sent_after_headers(self):
        sockets = []
        try:
            for _ in range(8):
                sockets.append(socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3))
            self.wait_active(8)
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as client:
                client.sendall(b'POST /v1/runs HTTP/1.1\r\nHost: localhost\r\n'
                               b'Content-Length: 12288\r\n\r\n')
                # The server has already responded, while the client is still
                # sending its body (as urllib/http.client can be doing).
                self.assertTrue(client.recv(4096, socket.MSG_PEEK).startswith(b'HTTP/1.1 503'))
                for _ in range(3):
                    time.sleep(.01)
                    client.sendall(b'x' * 4096)
                response = http.client.HTTPResponse(client)
                response.begin()
                self.assertEqual(response.status, 503)
                self.assertEqual(json.loads(response.read()), {'error': 'connection_limit'})
            self.assertEqual(self.server.peak, 8)
            self.assertEqual(list(Path(self.temp.name).glob('*.json')), [])
        finally:
            for connection in sockets:
                connection.close()
            self.wait_active(0)

    def test_overload_client_that_never_sends_cannot_block_accept_loop(self):
        sockets = []
        try:
            for _ in range(8):
                sockets.append(socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3))
            self.wait_active(8)
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as idle:
                self.assertTrue(idle.recv(4096, socket.MSG_PEEK).startswith(b'HTTP/1.1 503'))
                started = time.monotonic()
                self.assertEqual(self.request('GET', '/health')[0], 503)
                self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(self.server.peak, 8)
        finally:
            for connection in sockets:
                connection.close()
            self.wait_active(0)

    def test_rejected_trickle_cannot_extend_accept_loop_grace(self):
        sockets = []
        stop = threading.Event()
        sender = None
        try:
            for _ in range(8):
                sockets.append(socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3))
            self.wait_active(8)
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as client:
                self.assertTrue(client.recv(4096, socket.MSG_PEEK).startswith(b'HTTP/1.1 503'))
                sent = []
                def trickle():
                    while not stop.wait(.005):
                        try:
                            client.sendall(b'x')
                            sent.append(1)
                        except OSError:
                            return
                sender = threading.Thread(target=trickle, daemon=True)
                sender.start()
                started = time.monotonic()
                self.assertEqual(self.request('GET', '/health')[0], 503)
                self.assertLess(time.monotonic() - started, 1)
                self.assertGreaterEqual(len(sent), 2)
            self.assertEqual(self.server.peak, 8)
        finally:
            stop.set()
            if sender is not None:
                sender.join(timeout=2)
                self.assertFalse(sender.is_alive())
            for connection in sockets:
                connection.close()
            self.wait_active(0)

    def test_full_store_returns_507_and_retains_saved_report(self):
        self.server.store = ArtifactStore(self.temp.name, max_files=1)
        status, original = self.request('POST', '/v1/runs', self.scenario)
        self.assertEqual(status, 201)
        changed = {**self.scenario, 'title': 'A distinct synthetic example'}
        status, error = self.request('POST', '/v1/runs', changed)
        self.assertEqual((status, error['error']), (507, 'artifact_store_full'))
        self.assertEqual(self.request('GET', '/v1/runs/' + original['artifact_id']), (200, original))
        self.assertEqual(self.request('POST', '/v1/runs', self.scenario), (201, original))
        self.assertEqual(len(list(Path(self.temp.name).glob('*.json'))), 1)

    def test_slow_header_progress_does_not_extend_absolute_deadline(self):
        with patch('entrotter_engine.api.MAX_CONNECTION_SECONDS', .25):
            connection = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2)
            stop = threading.Event()
            sent = []
            def trickle():
                while not stop.wait(.03):
                    try:
                        connection.sendall(b' ')
                        sent.append(1)
                    except OSError:
                        return
            sender = threading.Thread(target=trickle, daemon=True)
            try:
                connection.sendall(b'GET /health HTTP/1.1\r\nX-Slow: ')
                self.wait_active(1)
                started = time.monotonic()
                sender.start()
                try:
                    self.assertEqual(connection.recv(1), b'')
                except ConnectionResetError:
                    # An absolute deadline intentionally aborts an incomplete
                    # request. Platforms may report FIN or reset when the peer
                    # is still writing; either proves closure, not a timeout.
                    pass
                self.assertLess(time.monotonic() - started, 1)
                self.assertGreaterEqual(len(sent), 3)
                self.wait_active(0)
            finally:
                stop.set()
                if sender.ident is not None:
                    sender.join(timeout=2)
                connection.close()
        self.assertEqual(self.request('GET', '/health')[0], 200)

    def test_exclusive_store_lock_returns_503_then_recovers(self):
        with self.server.store._locked():
            status, error = self.request('POST', '/v1/runs', self.scenario)
            self.assertEqual((status, error), (503, {'error': 'artifact_store_busy'}))
        self.assertEqual(self.request('POST', '/v1/runs', self.scenario)[0], 201)

    def test_oversized_stored_file_and_symlink_are_not_served(self):
        target = Path(self.temp.name) / ('f' * 64 + '.json')
        with target.open('wb') as f:
            f.truncate(MAX_REPORT_BYTES + 1)
        self.assertEqual(self.request('GET', '/v1/runs/' + 'f' * 64),
                         (500, {'error': 'invalid_stored_artifact'}))
        target.unlink()
        target.symlink_to(Path(self.temp.name) / '.store.lock')
        self.assertEqual(self.request('GET', '/v1/runs/' + 'f' * 64),
                         (500, {'error': 'invalid_stored_artifact'}))


if __name__ == '__main__':
    unittest.main()

"""Actual OS signals and Anvil subprocesses; these are not simulated lifecycle results."""
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest
from urllib.parse import urlsplit

from entrotter_engine.evm import AnvilSession, ExecutionError


@unittest.skipUnless(os.name == 'posix' and shutil.which('anvil'), 'POSIX and actual Anvil required')
class GuardianTests(unittest.TestCase):
    def assert_port_closed(self, url):
        with socket.socket() as sock:
            sock.settimeout(.2)
            self.assertNotEqual(sock.connect_ex(('127.0.0.1', urlsplit(url).port)), 0)

    def wait_until_closed(self, url, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                sock.settimeout(.1)
                if sock.connect_ex(('127.0.0.1', urlsplit(url).port)) != 0:
                    return
            time.sleep(.05)
        self.fail('Owned Anvil port remained open')

    def owner(self):
        code = '''import json,time
from entrotter_engine.evm import AnvilSession
with AnvilSession() as s:
    print(json.dumps({"guardian_pid":s.process.pid,"url":s.rpc.url}), flush=True)
    time.sleep(60)
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        process = subprocess.Popen([sys.executable, '-c', code], env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(10):
                process.kill()
                process.communicate(timeout=5)
                self.fail('Actual Anvil owner failed to become ready')
        data = json.loads(process.stdout.readline())
        return process, data

    def test_sigterm_and_sigkill_owner_close_the_owned_node(self):
        for sig in [signal.SIGTERM, signal.SIGKILL]:
            with self.subTest(signal=sig):
                process, data = self.owner()
                try:
                    os.kill(process.pid, sig)
                    process.communicate(timeout=5)
                    self.wait_until_closed(data['url'])
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
                    # Test-owned group only; also clean up after an assertion failure.
                    try:
                        os.killpg(data['guardian_pid'], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_lifetime_expires_without_owner_cooperation(self):
        session = AnvilSession(lifetime=1)
        try:
            session.__enter__()
            session.process.wait(timeout=4)
            self.assertEqual(session.process.returncode, 124)
            self.assert_port_closed(session.rpc.url)
        finally:
            session.__exit__(None, None, None)

    def test_killed_guardian_is_cleaned_by_owner_context(self):
        session = AnvilSession()
        session.__enter__()
        os.kill(session.process.pid, signal.SIGKILL)
        session.process.wait(timeout=5)
        session.__exit__(None, None, None)
        self.wait_until_closed(session.rpc.url)

    def test_ordinary_context_reaps_guardian_and_anvil(self):
        with AnvilSession() as session:
            self.assertIsNone(session.process.poll())
        self.assertEqual(session.process.returncode, 0)
        self.assertTrue(session.process.stdin.closed)
        self.assert_port_closed(session.rpc.url)


class GuardianInputTests(unittest.TestCase):
    def test_lifetime_cannot_be_unbounded_or_nonfinite(self):
        for value in [0, -1, 151, True, float('nan'), float('inf')]:
            with self.subTest(lifetime=value), self.assertRaises(ExecutionError):
                AnvilSession(lifetime=value)


if __name__ == '__main__':
    unittest.main()

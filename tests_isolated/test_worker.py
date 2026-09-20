"""Explicit real-Docker verification; not collected by the offline unit suite."""
import json
import os
from pathlib import Path
import signal
import subprocess
import unittest
import uuid

from entrotter_engine.isolated import client, run_isolated, worker_args, WORKER_NAME, WorkerBusy
from entrotter_engine.runner import run, run_native

ROOT = Path(__file__).resolve().parents[1]


class IsolatedWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = os.environ['ENTROTTER_WORKER_IMAGE']
        with client() as prefix:
            data = json.loads(subprocess.check_output([*prefix, 'info', '--format', '{{json .}}'], text=True))
        if data.get('CgroupVersion') != '2':
            raise RuntimeError('These enforcement checks require actual cgroup v2')

    def probe(self, code, *, memory='512m', pids=128, keep=False):
        name = 'entrotter-test-' + uuid.uuid4().hex
        with client() as prefix:
            args = worker_args(prefix, self.image, name)
            if keep:
                args.remove('--rm')
            args = [('--memory=' + memory) if x.startswith('--memory=') else
                    ('--memory-swap=' + memory) if x.startswith('--memory-swap=') else
                    ('--pids-limit=' + str(pids)) if x.startswith('--pids-limit=') else x for x in args]
            try:
                result = subprocess.run([*args[:-1], '--entrypoint=python3', args[-1], '-c', code],
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
                details = None
                if keep:
                    details = json.loads(subprocess.check_output([*prefix, 'inspect', name], text=True))[0]
                return result, details
            finally:
                subprocess.run([*prefix, 'rm', '--force', name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)

    def test_real_fixture_and_anvil_results_match_native(self):
        for name in ['fixture', 'local']:
            with self.subTest(case=name):
                scenario = json.loads((ROOT / f'tests/data/{name}.json').read_text())
                self.assertEqual(run(scenario), run_native(scenario))

    def test_kernel_controls_mounts_and_privileges(self):
        result, _ = self.probe('''import json,os
from pathlib import Path
c=Path('/sys/fs/cgroup')
print(json.dumps({"cpu":(c/'cpu.max').read_text().strip(),"memory":(c/'memory.max').read_text().strip(),"swap":(c/'memory.swap.max').read_text().strip(),"pids":(c/'pids.max').read_text().strip(),"readonly":bool(os.statvfs('/').f_flag & os.ST_RDONLY),"uid":os.getuid(),"status":Path('/proc/self/status').read_text()}))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        d = json.loads(result.stdout)
        self.assertEqual(d['cpu'], '100000 100000')
        self.assertEqual(d['memory'], str(512 * 1024 * 1024))
        self.assertEqual(d['swap'], '0')
        self.assertEqual(d['pids'], '128')
        self.assertTrue(d['readonly'])
        self.assertEqual(d['uid'], 65534)
        self.assertIn('CapEff:\t0000000000000000', d['status'])
        self.assertIn('NoNewPrivs:\t1', d['status'])
        self.assertIn('Seccomp:\t2', d['status'])

    def test_runtime_has_python_and_anvil_without_shell_or_package_commands(self):
        result, _ = self.probe('''import importlib.util,json,shutil,sys
print(json.dumps({"python":list(sys.version_info[:2]),"commands":{name:shutil.which(name) for name in ['anvil','sh','bash','apt','apk','pip','pip3']},"pip_importable":importlib.util.find_spec('pip') is not None}))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['python'], [3, 14])
        self.assertIsNotNone(observed['commands'].pop('anvil'))
        self.assertTrue(all(value is None for value in observed['commands'].values()))
        self.assertFalse(observed['pip_importable'])

    def test_memory_limit_actually_oom_kills_overallocation(self):
        result, details = self.probe('x=bytearray(128*1024*1024); print(len(x))', memory='64m', keep=True)
        self.assertEqual(result.returncode, 137)
        self.assertTrue(details['State']['OOMKilled'])
        self.assertEqual(details['HostConfig']['Memory'], 64 * 1024 * 1024)
        self.assertEqual(details['HostConfig']['MemorySwap'], 64 * 1024 * 1024)

    def test_pid_limit_actually_rejects_more_processes(self):
        result, _ = self.probe('''import os,signal,time,json,errno
children=[]; blocked=False
try:
    for _ in range(20):
        try: pid=os.fork()
        except OSError as error:
            blocked=error.errno==errno.EAGAIN
            break
        if pid==0:
            time.sleep(8); os._exit(0)
        children.append(pid)
    print(json.dumps({"blocked":blocked,"children":len(children)}),flush=True)
finally:
    for pid in children:
        try: os.kill(pid,signal.SIGKILL)
        except ProcessLookupError: pass
    for pid in children: os.waitpid(pid,0)
''', pids=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['blocked'])
        self.assertLessEqual(data['children'], 6)

    def test_tmpfs_space_and_noexec_are_enforced(self):
        result, _ = self.probe('''import errno,json,os,subprocess
from pathlib import Path
p=Path('/tmp/run.sh');p.write_text('#!/bin/sh\\nexit 0\\n');p.chmod(0o755)
noexec=False
try: subprocess.run([str(p)],check=True)
except PermissionError: noexec=True
full=False
try:
    with open('/tmp/large','wb') as f:
        for _ in range(70): f.write(b'x'*(1024*1024))
except OSError as e: full=e.errno==errno.ENOSPC
print(json.dumps({"noexec":noexec,"full":full}))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'noexec': True, 'full': True})

    def test_cpu_quota_throttles_parallel_work(self):
        result, _ = self.probe('''import json,multiprocessing,time
from pathlib import Path
p=Path('/sys/fs/cgroup/cpu.stat')
def stats(): return dict(line.split() for line in p.read_text().splitlines())
def busy():
    end=time.monotonic()+2
    while time.monotonic()<end: pass
before=stats(); context=multiprocessing.get_context('fork'); children=[context.Process(target=busy) for _ in range(3)]
for x in children: x.start()
for x in children: x.join()
after=stats();print(json.dumps({"throttled":int(after['nr_throttled'])-int(before['nr_throttled']),"exitcodes":[x.exitcode for x in children]}))
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        measured = json.loads(result.stdout)
        self.assertEqual(measured['exitcodes'], [0, 0, 0])
        self.assertGreater(measured['throttled'], 0)


class WorkerLifetimeTests(unittest.TestCase):
    def test_detached_idle_worker_expires_without_host_cooperation(self):
        import time
        image = os.environ['ENTROTTER_WORKER_IMAGE']
        name = WORKER_NAME
        scenario = json.loads((ROOT / 'tests/data/fixture.json').read_text())
        container = None
        with client() as prefix:
            args = worker_args(prefix, image, name)
            args.insert(-1, '--detach')
            start = time.monotonic()
            try:
                container = subprocess.check_output(args, stdin=subprocess.DEVNULL,
                                                    text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
                with self.assertRaises(WorkerBusy):
                    run(scenario)
                while time.monotonic() - start < 190:
                    active = subprocess.check_output(
                        [*prefix, 'ps', '--all', '--filter', 'name=^/' + name + '$', '--format', '{{.ID}}'],
                        text=True, timeout=5)
                    if not active.strip():
                        elapsed = time.monotonic() - start
                        self.assertGreater(elapsed, 175, 'Worker ended before timer; test did not exercise deadline')
                        print(f'Independent idle deadline observed after {elapsed:.3f} seconds', flush=True)
                        break
                    time.sleep(1)
                else:
                    self.fail('Worker timer did not remove detached idle container')
            finally:
                if container:
                    subprocess.run([*prefix, 'rm', '--force', container], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(run(scenario), run_native(scenario))

    def test_sigterm_ends_idle_worker_and_removes_container(self):
        self.check_lifetime(kill_client=False)

    def test_lost_client_is_bounded_by_independent_worker_timer(self):
        self.check_lifetime(kill_client=True)

    def check_lifetime(self, *, kill_client):
        import time
        image = os.environ['ENTROTTER_WORKER_IMAGE']
        name = 'entrotter-lifetime-' + uuid.uuid4().hex
        with client() as prefix:
            process = subprocess.Popen(worker_args(prefix, image, name), stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            start = time.monotonic()
            try:
                while time.monotonic() - start < 10:
                    state = subprocess.run([*prefix, 'inspect', '--format', '{{.State.Running}}', name],
                                           capture_output=True, text=True, timeout=5)
                    if state.returncode == 0 and state.stdout.strip() == 'true':
                        break
                    time.sleep(.1)
                else:
                    self.fail('Worker did not start')
                if kill_client:
                    process.kill()
                    process.wait(timeout=5)
                else:
                    subprocess.run([*prefix, 'kill', '--signal=TERM', name], check=True,
                                   stdout=subprocess.DEVNULL, timeout=5)
                deadline = start + (190 if kill_client else 10)
                while time.monotonic() < deadline:
                    active = subprocess.check_output(
                        [*prefix, 'ps', '--all', '--filter', 'name=^/' + name + '$', '--format', '{{.ID}}'],
                        text=True, timeout=5)
                    if not active.strip():
                        break
                    time.sleep(1)
                else:
                    self.fail('Owned worker outlived its deadline')
            finally:
                subprocess.run([*prefix, 'rm', '--force', name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                process.stdin.close()


class IsolatedAPITests(unittest.TestCase):
    def test_cli_and_api_roundtrip(self):
        import http.client
        import tempfile
        import threading
        import sys
        from entrotter_engine.api import EngineServer
        scenario = json.loads((ROOT / 'tests/data/local.json').read_text())
        expected = run_native(scenario)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'cli.json'
            subprocess.run([sys.executable, '-m', 'entrotter_engine', 'run',
                            str(ROOT / 'tests/data/local.json'), '-o', str(target)],
                           check=True, capture_output=True, timeout=30)
            self.assertEqual(json.loads(target.read_text()), expected)
            server = EngineServer(0, output=Path(directory) / 'api')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            try:
                connection.request('POST', '/v1/runs', json.dumps(scenario), {'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read()), expected)
                connection.request('GET', '/v1/runs/' + expected['artifact_id'])
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), expected)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()

"""Build input bounds; daemon access is replaced only in these unit tests."""

from contextlib import nullcontext
import ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import tarfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_worker", ROOT / "scripts/build_worker.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class WorkerBuildTests(unittest.TestCase):
    def simulated_image_preparation(self, dockerfile, *, rejected=False):
        """Real input copying/hashes/manifest; Docker and release identity simulated."""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);checkout=root/'checkout'
            (checkout/'container').mkdir(parents=True)
            (checkout/'container/Dockerfile').write_text(dockerfile)
            (checkout/'src/entrotter_engine').mkdir(parents=True)
            (checkout/'src/entrotter_engine/__init__.py').write_text('# synthetic test module\n')
            archive=root/'foundry.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                member=tarfile.TarInfo('anvil');member.size=4
                tar.addfile(member,io.BytesIO(b'test'))
            expected=hashlib.sha256(archive.read_bytes()).hexdigest()
            image='sha256:'+'a'*64;work=root/'build';work.mkdir()
            def docker(command,**kwargs):
                self.assertEqual(command[:2],['docker','build'])
                Path(command[command.index('--iidfile')+1]).write_text(image)
            with patch.object(builder,'ROOT',checkout), \
                 patch.object(builder,'ARCHIVES',{'x86_64':('amd64',expected)}), \
                 patch.object(builder,'verify_daemon',return_value={'Architecture':'x86_64'}), \
                 patch.object(builder,'run_build_command',side_effect=docker) as launch:
                if rejected:
                    with self.assertRaisesRegex(ValueError,'pinned base'):
                        builder.prepare_image(['docker'],work,archive)
                    launch.assert_not_called()
                    self.assertFalse((work/'manifest.json').exists())
                    return
                builder.prepare_image(['docker'],work,archive);launch.assert_called_once()
            result=json.loads((work/'manifest.json').read_text())
            self.assertEqual(result['image_id'],image)
            self.assertEqual(result['source_files']['Dockerfile'],hashlib.sha256(dockerfile.encode()).hexdigest())
            self.assertEqual((work/'context/Dockerfile').read_text(),dockerfile)
            self.assertEqual(result['source_digest'],hashlib.sha256(json.dumps(result['source_files'],sort_keys=True).encode()).hexdigest())
            return result

    def test_image_manifest_records_actual_copied_immutable_base(self):
        current=(ROOT/'container/Dockerfile').read_text()
        for dockerfile in [current,'FROM cgr.dev/chainguard/python@sha256:'+'b'*64+'\n']:
            with self.subTest(base=dockerfile.splitlines()[0]):
                result=self.simulated_image_preparation(dockerfile)
                self.assertEqual(result['base_image'],dockerfile.splitlines()[0].split()[1])

    def test_unpinned_or_ambiguous_base_refused_before_docker_build(self):
        base='FROM cgr.dev/chainguard/python@sha256:'+'b'*64
        for dockerfile in ['FROM cgr.dev/chainguard/python:latest\n',
            'FROM other/python@sha256:'+'b'*64+'\n',base[:-1]+'z\n',
            base+' AS build\n',base+'\nFROM other:latest\n',
            'ARG BASE\n'+base+'\n',base+'\nFRO\\\nM other:latest\n','']:
            with self.subTest(dockerfile=dockerfile):
                self.simulated_image_preparation(dockerfile,rejected=True)

    def test_noisy_command_has_bounded_diagnostics_and_preserves_failure(self):
        code = """import subprocess,sys
sys.path.insert(0,'scripts')
import build_worker as b
try:
    b.run_build_command([sys.executable,'-c',
        "import sys; sys.stdout.buffer.write(b'o'*(2*1024*1024)); sys.stdout.flush(); "
        "sys.stderr.buffer.write(b'e'*(2*1024*1024)); sys.stderr.flush(); sys.exit(7)"])
except subprocess.CalledProcessError as error:
    print('command-failed:'+str(error.returncode))
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2048:])
        self.assertEqual(result.stdout, b"command-failed:7\n")
        self.assertLessEqual(len(result.stderr), 1024 * 1024 + 256)
        self.assertIn(b"further build output discarded", result.stderr[-256:])

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process supervision")
    def test_endless_output_is_bounded_and_whole_deadline_cleans_session(self):
        code = """import sys,json,signal,subprocess,time
from pathlib import Path
sys.path.insert(0,'scripts')
import build_worker as b
def flooded(*args):
    child="import os,sys,signal; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); marker=Path(sys.argv[1]); pending=marker.with_suffix('.ready'); pending.write_text(str(os.getpgrp())); pending.replace(marker); exec('while True: os.write(1,b\\\"x\\\"*65536)')"
    b.run_build_command([sys.executable,'-c',child,sys.argv[1]],own_session=False)
b.prepare_image=flooded
started=time.monotonic()
try:
    with b.build_deadline(0.4):
        b.prepare_supervised([],Path(sys.argv[2]),None,0.4)
except ValueError:
    print(json.dumps({'deadline':True,'seconds':time.monotonic()-started}))
"""
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "group"
            result = subprocess.run(
                [sys.executable, "-c", code, str(marker), directory],
                cwd=ROOT,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2048:])
            self.assertTrue(marker.exists(), result.stderr[-2048:])
            observed = json.loads(result.stdout)
            self.assertTrue(observed["deadline"])
            self.assertLess(observed["seconds"], 2)
            self.assertLessEqual(len(result.stderr), 1024 * 1024 + 256)
            group = marker.read_text()
            deadline = time.monotonic() + 2
            while True:
                state = subprocess.run(
                    ["ps", "-eo", "pgid=,stat="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                active = [
                    line for line in state.stdout.splitlines()
                    if line.split()[0] == group and not line.split()[1].startswith("Z")
                ]
                if not active or time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
            self.assertFalse(active, active)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process supervision")
    def test_native_block_cannot_delay_the_supervised_deadline(self):
        def native_block(*args):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            # PyDLL holds the GIL during this native call. A Python thread/timer
            # in the same process is insufficient; the separate guardian kills it.
            ctypes.PyDLL(None).sleep(5)

        started = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(builder, "prepare_image", side_effect=native_block):
                with self.assertRaisesRegex(ValueError, "deadline"):
                    with builder.build_deadline(0.2):
                        builder.prepare_supervised([], Path(directory), None, 0.2)
        self.assertLess(time.monotonic() - started, 1.2)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process supervision")
    def test_owner_sigkill_closes_lifetime_pipe_and_stops_build_session(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pid"
            code = """import os,sys,time,signal
from pathlib import Path
sys.path.insert(0, 'scripts')
import build_worker as b
def stalled(*args):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    marker=Path(sys.argv[1]);pending=marker.with_suffix('.ready')
    pending.write_text(str(os.getpid()));pending.replace(marker)
    time.sleep(10)
b.prepare_image=stalled
b.prepare_supervised([], Path(sys.argv[2]), None, 10)
"""
            owner = subprocess.Popen([sys.executable, "-c", code, str(marker), directory], cwd=ROOT)
            try:
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "The supervised job never started")
                pid = int(marker.read_text())
                owner.kill()
                owner.wait(timeout=2)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    observed = subprocess.run(["ps", "-eo", "pgid=,stat="], capture_output=True, text=True, timeout=2)
                    active = [line for line in observed.stdout.splitlines() if line.split()[0] == str(pid) and not line.split()[1].startswith("Z")]
                    if not active:
                        break
                    time.sleep(0.02)
                self.assertFalse(active, active)
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=2)

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires POSIX timers")
    def test_real_stalled_http_body_is_interrupted(self):
        release = threading.Event()

        class Stalled(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                release.wait(5)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Stalled)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(ValueError, "deadline"):
                with builder.build_deadline(0.15):
                    with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                        response.read(100)
            self.assertLess(time.monotonic() - started, 0.8)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires POSIX timers")
    def test_timeout_kills_owned_command_and_term_ignoring_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-pid"
            code = """import os,signal,time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pid=os.fork()
if pid==0:
    marker=Path(%r);pending=marker.with_suffix('.ready')
    pending.write_text(str(os.getpid()));pending.replace(marker)
time.sleep(10)
""" % str(marker)
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "deadline"):
                with builder.build_deadline(0.5):
                    builder.run_build_command([sys.executable, "-c", code])
            self.assertLess(time.monotonic() - started, 3)
            self.assertTrue(marker.exists(), "The descendant never started")
            pid = int(marker.read_text())
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=2)
            self.assertTrue(not state.stdout.strip() or state.stdout.strip().startswith("Z"), state.stdout)

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires POSIX timers")
    def test_sigterm_cancels_and_restores_process_handlers(self):
        handlers = {signum: signal.getsignal(signum) for signum in [signal.SIGTERM, signal.SIGINT, signal.SIGALRM]}
        with self.assertRaisesRegex(KeyboardInterrupt, "cancelled"):
            with builder.build_deadline(3):
                builder.run_build_command([sys.executable, "-c", f"import os,signal,time; os.kill({os.getpid()}, signal.SIGTERM); time.sleep(10)"])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        self.assertEqual(handlers, {signum: signal.getsignal(signum) for signum in handlers})

    def test_manifest_failure_preserves_prior_bytes_without_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            target.write_text("previous manifest")
            with patch.object(builder.os, "replace", side_effect=OSError("failed")):
                with self.assertRaisesRegex(OSError, "failed"):
                    builder.write_manifest(target, {"image_id": "new"})
            self.assertEqual(target.read_text(), "previous manifest")
            self.assertEqual(list(Path(directory).iterdir()), [target])
            builder.write_manifest(target, {"image_id": "new"})
            self.assertIn('"image_id": "new"', target.read_text())

    def test_invalid_budgets_are_rejected_before_allocating_resources(self):
        for seconds in ["0", "-1", "601", "nan", "inf"]:
            with self.subTest(seconds=seconds), patch("sys.argv", ["build_worker", "--timeout-seconds", seconds]):
                with self.assertRaises(SystemExit) as caught:
                    builder.main()
                self.assertEqual(caught.exception.code, 2)

    @unittest.skipUnless(hasattr(signal, "setitimer"), "requires POSIX timers")
    def test_blocked_download_obeys_whole_build_budget_and_preserves_manifest(self):
        def blocked_download(*args, **kwargs):
            time.sleep(2)
            raise ValueError("download finally returned")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "manifest.json"
            output.write_text("previous manifest")
            started = time.monotonic()
            with (
                patch.object(builder, "BUILD_SECONDS", 0.15, create=True),
                patch.object(builder, "client", return_value=nullcontext([])),
                patch.object(builder, "verify_daemon", return_value={"Architecture": "aarch64"}),
                patch.object(builder, "urlopen", side_effect=blocked_download),
                patch("sys.argv", ["build_worker", "--output", str(output)]),
                self.assertRaisesRegex(ValueError, "deadline"),
            ):
                builder.main()
            self.assertLess(time.monotonic() - started, 0.8)
            self.assertEqual(output.read_text(), "previous manifest")

    def test_exact_limit_is_accepted_and_hash_is_preserved(self):
        payload = b"verified release bytes"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "archive"
            with patch.object(builder, "MAX_ARCHIVE_BYTES", len(payload)):
                builder.copy_verified_archive(
                    io.BytesIO(payload), target, hashlib.sha256(payload).hexdigest()
                )
            self.assertEqual(target.read_bytes(), payload)

    def test_endless_stream_cannot_fill_disk_or_request_unbounded_reads(self):
        class Endless:
            def read(self, size):
                self_case.assertGreater(size, 0)
                self_case.assertLessEqual(size, builder.READ_BYTES)
                return b"x" * size

        self_case = self
        limit = 2 * builder.READ_BYTES
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "archive"
            with (
                patch.object(builder, "MAX_ARCHIVE_BYTES", limit),
                self.assertRaisesRegex(ValueError, "archive exceeds"),
            ):
                builder.copy_verified_archive(Endless(), target, "unused")
            self.assertEqual(target.stat().st_size, limit)

    def test_corrupt_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                builder.copy_verified_archive(
                    io.BytesIO(b"changed"),
                    Path(directory) / "archive",
                    hashlib.sha256(b"original").hexdigest(),
                )

    def test_deadline_checks_after_slow_read_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "archive"
            with (
                patch.object(
                    builder.time,
                    "monotonic",
                    side_effect=[0, 1, builder.ARCHIVE_SECONDS],
                ),
                self.assertRaisesRegex(ValueError, "deadline exceeded"),
            ):
                builder.copy_verified_archive(io.BytesIO(b"late"), target, "unused")
            self.assertEqual(target.stat().st_size, 0)

    def test_local_regular_file_is_streamed_without_read_bytes(self):
        payload = b"local release bytes"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            target = Path(directory) / "archive"
            source.write_bytes(payload)
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("whole-file read")
            ):
                builder.stage_local_archive(
                    source, target, hashlib.sha256(payload).hexdigest()
                )
            self.assertEqual(target.read_bytes(), payload)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_fifo_without_writer_rejects_without_hanging(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "fifo"
            os.mkfifo(fifo)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; from pathlib import Path; sys.path.insert(0, 'scripts'); from build_worker import stage_local_archive; stage_local_archive(Path(sys.argv[1]), Path(sys.argv[2]), 'unused')",
                    str(fifo),
                    str(Path(directory) / "target"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be a regular file", result.stderr)

    @unittest.skipUnless(os.name == "posix", "requires owned fork watchdog")
    def test_early_failed_job_reaps_watchdog_before_signal_initialization(self):
        # Force the exact fork initialization gap. An inherited handler can
        # consume SIGTERM before guard_build installs default signal handling.
        script = r'''
from contextlib import nullcontext
import json,os,signal,sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'scripts')
import build_worker as builder
root=Path(sys.argv[1]);parent=os.getpid();marker=root/'watchdog';job=root/'job'
def publish(path, text):
    pending=path.with_suffix('.ready')
    pending.write_text(text);pending.replace(path)
def gap():
    if os.getppid()!=parent:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        publish(marker,str(os.getpid()))
        time.sleep(.6)
os.register_at_fork(after_in_child=gap)
def reject(*args):
    publish(job,str(os.getpid()))
    end=time.monotonic()+1
    while not marker.exists() and time.monotonic()<end:time.sleep(.005)
    raise ValueError('Synthetic early archive rejection')
started=time.monotonic();error=None
try:
    with patch.object(builder,'prepare_image',side_effect=reject),patch.object(builder,'client',return_value=nullcontext([])),patch('sys.argv',['build_worker','--timeout-seconds','2','--output',str(root/'result')]):
        builder.main()
except ValueError as failure:
    error=str(failure)
print(json.dumps({'seconds':time.monotonic()-started,'error':error,'pids':[int(job.read_text()),int(marker.read_text())]}))
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", script, directory], cwd=ROOT,
                                    capture_output=True, text=True, timeout=6,
                                    start_new_session=True)
            self.assertEqual(result.returncode, 0)
            observed = json.loads(result.stdout)
            self.assertEqual(observed["error"], "Synthetic early archive rejection")
            self.assertLess(observed["seconds"], .6)
            for pid in observed["pids"]:
                end = time.monotonic()+2
                while time.monotonic()<end:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.01)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_oversized_archive_rejected_before_digest_or_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "archive"
            source.write_bytes(b"12345")
            output = Path(directory) / "manifest.json"
            output.write_text("previous manifest")
            with (
                patch.object(builder, "MAX_ARCHIVE_BYTES", 4, create=True),
                patch.object(builder, "client", return_value=nullcontext([])),
                patch.object(
                    builder, "verify_daemon", return_value={"Architecture": "aarch64"}
                ),
                patch(
                    "sys.argv",
                    ["build_worker", "--archive", str(source), "--output", str(output)],
                ),
                self.assertRaisesRegex(ValueError, "archive exceeds"),
            ):
                builder.main()
            self.assertEqual(output.read_text(), "previous manifest")


if __name__ == "__main__":
    unittest.main()

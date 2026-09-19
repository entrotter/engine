"""Opt-in bounded local Docker execution. All image/socket settings are operator-owned."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from .artifact import canonical, verify
from .evm import ExecutionError
from .models import validate

MAX_OUTPUT = 8 * 1024 * 1024
MAX_INPUT = 262144
HOST_TIMEOUT = 190


@contextmanager
def client():
    binary = shutil.which('docker')
    socket = Path(os.environ.get('ENTROTTER_DOCKER_SOCKET', '/var/run/docker.sock'))
    if not binary or not socket.is_absolute():
        raise ExecutionError('A local Docker CLI and absolute Unix socket are required')
    try:
        if not stat.S_ISSOCK(socket.stat().st_mode):
            raise ValueError()
    except (OSError, ValueError):
        raise ExecutionError('Configure ENTROTTER_DOCKER_SOCKET to a running local Docker daemon') from None
    # Public/local worker images require no access to the user's registry credentials.
    with tempfile.TemporaryDirectory(prefix='entrotter-docker-client-') as config:
        yield [binary, '--config', config, '--host', 'unix://' + str(socket)]


def worker_args(prefix, image, name, *, fork=False):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ExecutionError('ENTROTTER_WORKER_IMAGE must be a built immutable image ID')
    args = [*prefix, 'run', '--rm', '--interactive', '--init', '--pull=never',
            '--name', name, '--label', 'org.entrotter.worker=true',
            '--cpus=1', '--memory=512m', '--memory-swap=512m', '--pids-limit=128',
            '--read-only', '--shm-size=16m', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            '--cap-drop=ALL', '--security-opt=no-new-privileges=true',
            '--log-driver=none', '--user=65534:65534', '--workdir=/app']
    if fork:
        # This enables archive reads for trusted built-in execution. It is not an
        # egress firewall for arbitrary code, which remains unavailable.
        args += ['--network=bridge', '--env', 'ENTROTTER_RPC_URL']
    else:
        args += ['--network=none']
    return [*args, image]


def verify_daemon(prefix):
    try:
        result = subprocess.run([*prefix, 'info', '--format', '{{json .}}'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=10, check=True)
        info = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ExecutionError('Cannot verify local Docker resource controllers') from None
    if (not isinstance(info, dict) or info.get('OSType') != 'linux'
            or info.get('CgroupVersion') != '2'
            or not all(info.get(field) is True for field in
                       ['MemoryLimit', 'SwapLimit', 'CpuCfsQuota', 'PidsLimit'])):
        raise ExecutionError('Local Linux cgroup v2 CPU/memory/swap/PID controllers are required')
    return info


def run_isolated(scenario):
    validate(scenario)
    payload = canonical(scenario)
    if len(payload) > MAX_INPUT:
        raise ExecutionError('Isolated scenario exceeds 256 KiB')
    image = os.environ.get('ENTROTTER_WORKER_IMAGE', '')
    name = 'entrotter-run-' + uuid.uuid4().hex
    with client() as prefix, tempfile.TemporaryFile() as stdin:
        args = worker_args(prefix, image, name, fork=scenario['mode'] == 'evm-fork')
        verify_daemon(prefix)
        stdin.write(payload)
        stdin.seek(0)
        process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + HOST_TIMEOUT
        output = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ExecutionError('Isolated experiment timed out')
                    for key, _ in selector.select(min(.1, remaining)):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            output.extend(chunk)
                            if len(output) > MAX_OUTPUT:
                                raise ExecutionError('Isolated report exceeds 8 MiB')
            try:
                code = process.wait(timeout=max(.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ExecutionError('Isolated experiment timed out') from None
            if code != 0:
                raise ExecutionError('Isolated worker failed or exceeded its resource budget; no fallback')
            try:
                report = json.loads(output)
            except (ValueError, UnicodeError, RecursionError):
                raise ExecutionError('Invalid isolated worker response') from None
            if not verify(report) or report.get('scenario') != json.loads(payload):
                raise ExecutionError('Isolated response integrity or scenario binding failed')
            return report
        finally:
            # Normal cancellation and timeout request deletion of this exact owned
            # container. SIGKILL of this client is additionally bounded by the
            # worker's independent in-container lifetime timer and --rm.
            cleanup_failed = False
            try:
                subprocess.run([*prefix, 'rm', '--force', name], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                remaining = subprocess.run(
                    [*prefix, 'ps', '--all', '--filter', 'name=^/' + name + '$', '--format', '{{.ID}}'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                cleanup_failed = remaining.returncode != 0 or bool(remaining.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                process.stdout.close()
            if cleanup_failed:
                raise ExecutionError('Local Docker cleanup could not be confirmed; inspect owned workers') from None

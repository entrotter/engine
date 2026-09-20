"""Default bounded local Docker execution. All image/socket settings are operator-owned."""

from contextlib import contextmanager
from hashlib import sha256
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
WORKER_NAME = "entrotter-active-worker"
OWNER_LABEL = "org.entrotter.owner"


class WorkerBusy(ExecutionError):
    """The configured daemon's single worker slot is already occupied."""


def _slot(prefix, owner=None):
    args = [
        *prefix,
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "name=^/" + WORKER_NAME + "$",
    ]
    if owner is not None:
        args += ["--filter", "label=" + OWNER_LABEL + "=" + owner]
    try:
        result = subprocess.run(
            [*args, "--format", "{{.ID}}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
        value = result.stdout.decode("ascii").strip()
        if value and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError()
        return value or None
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ExecutionError("Cannot verify local Docker worker admission") from None


def _cleanup(prefix, owner):
    try:
        container = _slot(prefix, owner)
        if container is not None:
            subprocess.run(
                [*prefix, "rm", "--force", container],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        if _slot(prefix, owner) is not None:
            raise ExecutionError("Owned worker remains")
    except (OSError, subprocess.SubprocessError, ExecutionError):
        raise ExecutionError(
            "Local Docker cleanup could not be confirmed; inspect owned workers"
        ) from None


@contextmanager
def client():
    binary = shutil.which("docker")
    socket = Path(os.environ.get("ENTROTTER_DOCKER_SOCKET", "/var/run/docker.sock"))
    if not binary or not socket.is_absolute():
        raise ExecutionError("A local Docker CLI and absolute Unix socket are required")
    try:
        if not stat.S_ISSOCK(socket.stat().st_mode):
            raise ValueError()
    except (OSError, ValueError):
        raise ExecutionError(
            "Configure ENTROTTER_DOCKER_SOCKET to a running local Docker daemon"
        ) from None
    # Public/local worker images require no access to the user's registry credentials.
    with tempfile.TemporaryDirectory(prefix="entrotter-docker-client-") as config:
        yield [binary, "--config", config, "--host", "unix://" + str(socket)]


def worker_args(prefix, image, name, *, fork=False):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ExecutionError(
            "ENTROTTER_WORKER_IMAGE must be a built immutable image ID"
        )
    args = [
        *prefix,
        "run",
        "--rm",
        "--interactive",
        "--init",
        "--pull=never",
        "--name",
        name,
        "--label",
        "org.entrotter.worker=true",
        "--cpus=1",
        "--memory=512m",
        "--memory-swap=512m",
        "--pids-limit=128",
        "--read-only",
        "--shm-size=16m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--log-driver=none",
        "--user=65534:65534",
        "--workdir=/app",
    ]
    if fork:
        # This enables archive reads for trusted built-in execution. It is not an
        # egress firewall for arbitrary code, which remains unavailable.
        args += ["--network=bridge", "--env", "ENTROTTER_RPC_URL"]
    else:
        args += ["--network=none"]
    return [*args, image]


def verify_daemon(prefix):
    try:
        result = subprocess.run(
            [*prefix, "info", "--format", "{{json .}}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
        info = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ExecutionError(
            "Cannot verify local Docker resource controllers"
        ) from None
    if (
        not isinstance(info, dict)
        or info.get("OSType") != "linux"
        or info.get("CgroupVersion") != "2"
        or not all(
            info.get(field) is True
            for field in ["MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit"]
        )
    ):
        raise ExecutionError(
            "Local Linux cgroup v2 CPU/memory/swap/PID controllers are required"
        )
    return info


def run_isolated(scenario):
    validate(scenario)
    payload = canonical(scenario)
    if len(payload) > MAX_INPUT:
        raise ExecutionError("Isolated scenario exceeds 256 KiB")
    # Bind verification and network selection to the admitted snapshot as well.
    return _run_worker(json.loads(payload), payload)


def run_agent_isolated(scenario: dict, configuration: dict) -> dict:
    from .worker_protocol import encode_agent_request

    payload = encode_agent_request(scenario, configuration)
    snapshot = json.loads(payload)
    return _run_worker(
        snapshot["scenario"], payload, request_id=sha256(payload).hexdigest()
    )


def _run_worker(
    scenario: dict, payload: bytes, *, request_id: str | None = None
) -> dict:
    image = os.environ.get("ENTROTTER_WORKER_IMAGE", "")
    owner = uuid.uuid4().hex
    with client() as prefix, tempfile.TemporaryFile() as stdin:
        args = worker_args(
            prefix, image, WORKER_NAME, fork=scenario["mode"] == "evm-fork"
        )
        args[len(prefix) + 1 : len(prefix) + 1] = [
            "--label",
            OWNER_LABEL + "=" + owner,
        ]
        verify_daemon(prefix)
        if _slot(prefix) is not None:
            raise WorkerBusy(
                "Local Docker worker busy; retry deliberately after completion"
            )
        stdin.write(payload)
        stdin.seek(0)
        process = subprocess.Popen(
            args,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + HOST_TIMEOUT
        output = bytearray()
        stream = process.stdout
        try:
            if stream is None:
                raise ExecutionError("Worker output pipe was not initialized")
            with selectors.DefaultSelector() as selector:
                selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ExecutionError("Isolated experiment timed out")
                    for key, _ in selector.select(min(0.1, remaining)):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            output.extend(chunk)
                            if len(output) > MAX_OUTPUT:
                                raise ExecutionError("Isolated report exceeds 8 MiB")
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ExecutionError("Isolated experiment timed out") from None
            if code != 0:
                # Name reservation can reject a contender before the winner is
                # visible to ps. Do not infer safe retry or completed admission
                # from a Docker exit code; all ambiguous failures stay explicit.
                raise ExecutionError(
                    "Isolated worker failed or exceeded its resource budget; no fallback"
                )
            try:
                report = json.loads(output)
            except (ValueError, UnicodeError, RecursionError):
                raise ExecutionError("Invalid isolated worker response") from None
            if request_id is not None:
                from .agent import AgentError, ReplayPolicy
                from .worker_protocol import WORKER_VERSION

                if (
                    not isinstance(report, dict)
                    or set(report) != {"worker_version", "request_id", "report"}
                    or report["worker_version"] != WORKER_VERSION
                    or report["request_id"] != request_id
                ):
                    raise ExecutionError("Agent worker request binding failed")
                report = report["report"]
                try:
                    if not isinstance(report, dict) or not isinstance(
                        report.get("agent"), dict
                    ):
                        raise AgentError("Missing agent recording")
                    ReplayPolicy(report["agent"])
                except AgentError:
                    raise ExecutionError("Invalid agent worker recording") from None
            elif isinstance(report, dict) and "agent" in report:
                raise ExecutionError("Unexpected agent worker response")
            if not verify(report) or report.get("scenario") != scenario:
                raise ExecutionError(
                    "Isolated response integrity or scenario binding failed"
                )
            return report
        finally:
            # Stop the client before checking ownership. Never remove by the
            # shared slot name: a race loser or an old finalizer must not kill a
            # different invocation. Auto-removal may race removal of our exact ID.
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            finally:
                if stream is not None:
                    stream.close()
                _cleanup(prefix, owner)

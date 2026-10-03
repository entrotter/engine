#!/usr/bin/env python3
"""Build a local immutable worker image from pinned upstream inputs and this checkout."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import BinaryIO
from urllib.request import Request, urlopen

from entrotter_engine.isolated import client, verify_daemon

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
ARCHIVE_SECONDS = 300
BUILD_SECONDS = 600
READ_BYTES = 1024 * 1024
MAX_BUILD_LOG_BYTES = 1024 * 1024
LOG_READ_BYTES = 64 * 1024
ARCHIVES = {
    "aarch64": (
        "arm64",
        "93fc23be26c8a902ca58fe54aa6ca28c880b58af95d052674933161df7928e6d",
    ),
    "x86_64": (
        "amd64",
        "7ca48e6ca3cac1bce1403ca67e5bc1dc3bc1fd818199c9957c7165079c228568",
    ),
}


@contextmanager
def build_deadline(seconds: float):
    """Interrupt the POSIX CLI's entire build, including a blocked network read."""
    if not hasattr(signal, "setitimer"):
        raise ValueError("Worker image preparation requires POSIX interval timers")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ValueError("Cannot replace an existing process timer")

    def expired(signum, frame):
        raise ValueError("Worker build deadline exceeded")

    def cancelled(signum, frame):
        raise KeyboardInterrupt("Worker build cancelled")

    previous = {
        signum: signal.getsignal(signum)
        for signum in [signal.SIGALRM, signal.SIGTERM, signal.SIGINT]
    }
    try:
        signal.signal(signal.SIGALRM, expired)
        signal.signal(signal.SIGTERM, cancelled)
        signal.signal(signal.SIGINT, cancelled)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_build_command(command: list[str], *, own_session: bool = True) -> None:
    """Bound streamed diagnostics; keep the fixed CLI in its owned session."""
    with subprocess.Popen(
        command,
        start_new_session=own_session,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as process:
        try:
            if process.stdout is None:
                raise ValueError("Build diagnostic pipe was not created")
            remaining = MAX_BUILD_LOG_BYTES
            truncated = False
            while chunk := os.read(process.stdout.fileno(), LOG_READ_BYTES):
                visible = chunk[:remaining]
                if visible:
                    sys.stderr.buffer.write(visible)
                    sys.stderr.buffer.flush()
                    remaining -= len(visible)
                if len(visible) < len(chunk) and not truncated:
                    sys.stderr.buffer.write(
                        b"\nEntrotter: 1 MiB diagnostic limit; further build output discarded.\n"
                    )
                    sys.stderr.buffer.flush()
                    truncated = True
                # Continue draining in bounded chunks, without buffering or
                # blocking the producer after the output allowance is used.
                # The existing independent whole-build deadline still applies.
            status = process.wait()
            if status:
                raise subprocess.CalledProcessError(status, command)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            # The CLI may exit before a descendant that ignores SIGTERM.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=1)
            raise


def write_manifest(output: Path, result: dict) -> None:
    """A failed write or expired deadline must not truncate an existing manifest."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=output.parent, prefix=".entrotter-manifest-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(result, indent=2) + "\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_verified_archive(source: BinaryIO, target: Path, expected: str) -> None:
    """Bound staged bytes and memory before trusting or extracting an archive."""
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + ARCHIVE_SECONDS
    # HTTP read1 returns available data without filling a large read buffer.
    read = getattr(source, "read1", source.read)
    with target.open("wb") as output:
        while True:
            if time.monotonic() >= deadline:
                raise ValueError("Foundry archive transfer deadline exceeded")
            chunk = read(min(READ_BYTES, MAX_ARCHIVE_BYTES - total + 1))
            if time.monotonic() >= deadline:
                raise ValueError("Foundry archive transfer deadline exceeded")
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("Foundry archive exceeds 256 MiB")
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Foundry release archive digest mismatch")


def stage_local_archive(source: Path, target: Path, expected: str) -> None:
    # Opening a FIFO normally can block before its file type can be checked.
    descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Foundry archive must be a regular file")
        if info.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Foundry archive exceeds 256 MiB")
        # The streaming bound still applies if a regular source grows after fstat.
        copy_verified_archive(stream, target, expected)


def guard_build(owner_read: int, budget: float) -> None:
    """Kill the owned build session on owner-pipe EOF or a wall-clock expiry."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    deadline = time.monotonic() + budget
    with selectors.DefaultSelector() as selector:
        selector.register(owner_read, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or selector.select(remaining):
                os.killpg(os.getpgrp(), signal.SIGKILL)


def preparation_job(
    prefix, root, archive, budget, owner_read, owner_write, receiver, sender, ready
):
    os.close(owner_write)
    receiver.close()
    os.setsid()
    ready.set()
    watchdog = os.fork()
    if watchdog == 0:
        sender.close()
        try:
            guard_build(owner_read, budget)
        finally:
            os._exit(1)
    os.close(owner_read)
    try:
        prepare_image(prefix, root, archive)
        sender.send(None)
    except BaseException as error:
        sender.send(str(error)[:2048])
    finally:
        sender.close()
        # This PID remains our unreaped child; it cannot be reused here. SIGTERM
        # may hit inherited handlers inside Python's after-fork initialization,
        # before guard_build resets them. SIGKILL cannot be consumed in that gap.
        try:
            os.kill(watchdog, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(watchdog, 0)


def prepare_supervised(
    prefix: list[str], root: Path, archive: Path | None, budget: float
) -> None:
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)
    owner_read, owner_write = os.pipe()
    ready = context.Event()
    job = context.Process(
        target=preparation_job,
        args=(
            prefix,
            root,
            archive,
            budget,
            owner_read,
            owner_write,
            receiver,
            sender,
            ready,
        ),
    )
    try:
        job.start()
        os.close(owner_read)
        owner_read = -1
        sender.close()
        job.join()
        if job.exitcode != 0 or not receiver.poll():
            raise ValueError("Worker build failed or deadline exceeded")
        error = receiver.recv()
        if error is not None:
            raise ValueError(error)
    finally:
        # EOF also stops the independent watchdog if the owner is SIGKILLed.
        os.close(owner_write)
        if owner_read != -1:
            os.close(owner_read)
        sender.close()
        receiver.close()
        if job.pid is not None:
            # The independent watchdog receives EOF and kills the complete owned
            # session. Do not signal a reaped leader's already vanished group.
            job.join(timeout=1)
            if job.is_alive():
                if ready.is_set():
                    try:
                        os.killpg(job.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    job.kill()
                job.join(timeout=1)
            if job.is_alive():
                raise RuntimeError("Owned build cleanup could not be confirmed")
            job.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use an already downloaded archive, still digest-verified",
    )
    parser.add_argument("--output", type=Path, default=Path("worker-image.json"))
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=BUILD_SECONDS,
        help="Whole preparation budget, greater than zero and at most 600 seconds",
    )
    args = parser.parse_args()
    if (
        not math.isfinite(args.timeout_seconds)
        or not 0 < args.timeout_seconds <= BUILD_SECONDS
    ):
        parser.error("--timeout-seconds must be greater than zero and at most 600")
    with (
        build_deadline(args.timeout_seconds),
        client() as prefix,
        tempfile.TemporaryDirectory(prefix="entrotter-worker-build-") as directory,
    ):
        root = Path(directory)
        prepare_supervised(prefix, root, args.archive, args.timeout_seconds)
        result = json.loads((root / "manifest.json").read_text())
        write_manifest(args.output, result)
        print(
            json.dumps(
                {
                    "image_id": result["image_id"],
                    "manifest": str(args.output),
                    "published": False,
                }
            )
        )


def prepare_image(
    prefix: list[str], directory: Path, archive_source: Path | None
) -> None:
    info = verify_daemon(prefix)
    architecture, expected = ARCHIVES[info["Architecture"]]
    root = directory
    archive = root / "foundry.tar.gz"
    if archive_source:
        stage_local_archive(archive_source, archive, expected)
    else:
        url = f"https://github.com/foundry-rs/foundry/releases/download/v1.8.3/foundry_v1.8.3_linux_{architecture}.tar.gz"
        with (
            urlopen(
                Request(url, headers={"User-Agent": "Entrotter/0.1.0"}), timeout=10
            ) as response,
        ):
            copy_verified_archive(response, archive, expected)
    context = root / "context"
    context.mkdir()
    with tarfile.open(archive) as tar:
        member = next(m for m in tar.getmembers() if m.name == "anvil" and m.isfile())
        source = tar.extractfile(member)
        if source is None:
            raise ValueError("Verified archive has no regular Anvil executable")
        with source, (context / "anvil").open("wb") as target:
            shutil.copyfileobj(source, target)
    (context / "anvil").chmod(0o755)
    package = context / "entrotter_engine"
    package.mkdir()
    sources = {}
    for path in sorted((ROOT / "src/entrotter_engine").glob("*.py")):
        shutil.copyfile(path, package / path.name)
        sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.copyfile(ROOT / "container/Dockerfile", context / "Dockerfile")
    base_image = pinned_base_image(context / "Dockerfile")
    sources["Dockerfile"] = hashlib.sha256(
        (context / "Dockerfile").read_bytes()
    ).hexdigest()
    source_digest = hashlib.sha256(
        json.dumps(sources, sort_keys=True).encode()
    ).hexdigest()
    iid = root / "image-id"
    run_build_command(
        [
            *prefix,
            "build",
            "--iidfile",
            str(iid),
            "--label",
            "org.entrotter.source=" + source_digest,
            "--tag",
            "entrotter-worker:" + source_digest[:16],
            str(context),
        ],
        own_session=False,
    )
    image_id = iid.read_text().strip()
    with (context / "anvil").open("rb") as binary:
        anvil_digest = hashlib.file_digest(binary, "sha256").hexdigest()
    result = {
        "image_id": image_id,
        "source_digest": source_digest,
        "source_files": sources,
        "foundry_version": "1.8.3",
        "foundry_archive_sha256": expected,
        "anvil_binary_sha256": anvil_digest,
        "architecture": architecture,
        "published": False,
        "base_image": base_image,
    }
    write_manifest(root / "manifest.json", result)


def pinned_base_image(dockerfile: Path) -> str:
    """Bind provenance to the copied flat, single-stage immutable Python base."""
    lines = dockerfile.read_text().splitlines()
    first = lines[0] if lines else ""
    prefix = "FROM cgr.dev/chainguard/python@sha256:"
    digest = first.removeprefix(prefix)
    directives = [line.split(maxsplit=1)[0].upper() for line in lines if line.strip()]
    if (
        not first.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or directives.count("FROM") != 1
        or any(line.rstrip().endswith("\\") for line in lines)
    ):
        raise ValueError("Worker Dockerfile must use one immutable pinned base")
    return first.removeprefix("FROM ")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a local immutable worker image from pinned upstream inputs and this checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from typing import BinaryIO
from urllib.request import Request, urlopen

from entrotter_engine.isolated import client, verify_daemon

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
ARCHIVE_SECONDS = 300
READ_BYTES = 1024 * 1024
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use an already downloaded archive, still digest-verified",
    )
    parser.add_argument("--output", type=Path, default=Path("worker-image.json"))
    args = parser.parse_args()
    with (
        client() as prefix,
        tempfile.TemporaryDirectory(prefix="entrotter-worker-build-") as directory,
    ):
        info = verify_daemon(prefix)
        architecture, expected = ARCHIVES[info["Architecture"]]
        root = Path(directory)
        archive = root / "foundry.tar.gz"
        if args.archive:
            stage_local_archive(args.archive, archive, expected)
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
            member = next(
                m for m in tar.getmembers() if m.name == "anvil" and m.isfile()
            )
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
        sources["Dockerfile"] = hashlib.sha256(
            (context / "Dockerfile").read_bytes()
        ).hexdigest()
        source_digest = hashlib.sha256(
            json.dumps(sources, sort_keys=True).encode()
        ).hexdigest()
        iid = root / "image-id"
        subprocess.run(
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
            check=True,
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
            "base_image": "cgr.dev/chainguard/python@sha256:011e73b4e30e0fe9407a42b82a920b4fa13ebc0bf029a48b714f950df254ca20",
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {"image_id": image_id, "manifest": str(args.output), "published": False}
            )
        )


if __name__ == "__main__":
    main()

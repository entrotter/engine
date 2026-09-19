"""Bounded dedicated API report directory, serialized across local POSIX writers.

The operator owns the directory. These application quotas do not constrain other
programs modifying it or provide a quota for the host filesystem/VM image.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .artifact import MAX_REPORT_BYTES, canonical, verify

MAX_STORE_BYTES = 128 * 1024 * 1024
MAX_STORE_FILES = 128


class StoreFull(OSError):
    pass


class StoreBusy(OSError):
    pass


class ArtifactStore:
    def __init__(self, root, *, max_bytes=MAX_STORE_BYTES, max_files=MAX_STORE_FILES):
        if os.name != "posix":
            raise OSError("The bounded local API store requires POSIX file locking")
        if (
            type(max_bytes) is not int
            or type(max_files) is not int
            or min(max_bytes, max_files) <= 0
        ):
            raise ValueError("Store limits must be positive integers")
        self.root = Path(root).resolve()
        self.max_bytes, self.max_files = max_bytes, max_files
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._usage()

    @contextmanager
    def _locked(self):
        import fcntl

        descriptor = os.open(
            self.root / ".store.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size or info.st_nlink != 1:
                raise OSError("Invalid artifact store lock")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StoreBusy("Artifact store is busy") from None
            yield
        finally:
            os.close(descriptor)

    def _usage(self):
        total, count = 0, 0
        with os.scandir(self.root) as entries:
            for entry in entries:
                if entry.name == ".store.lock":
                    continue
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError(
                        "Artifact directory must contain only regular, singly linked files"
                    )
                # Account for unrelated and crash-leftover files too. Never prune
                # operator data automatically to make a failed write appear valid.
                total += info.st_size
                count += 1
                if total > self.max_bytes or count > self.max_files:
                    raise StoreFull("Artifact store quota exceeded")
        return total, count

    def _path(self, artifact_id):
        if not isinstance(artifact_id, str) or not re.fullmatch(
            r"[a-f0-9]{64}", artifact_id
        ):
            raise ValueError("Invalid artifact ID")
        return self.root / (artifact_id + ".json")

    def get(self, artifact_id):
        path = self._path(artifact_id)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > MAX_REPORT_BYTES
            ):
                raise ValueError("Invalid stored artifact")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw = source.read(MAX_REPORT_BYTES + 1)
            if len(raw) > MAX_REPORT_BYTES:
                raise ValueError("Stored artifact exceeds report size limit")
            report = json.loads(raw)
            if not verify(report) or report["artifact_id"] != artifact_id:
                raise ValueError("Stored artifact ID mismatch")
            return report
        finally:
            os.close(descriptor)

    def put(self, report):
        if not verify(report):
            raise ValueError("Refusing to store invalid report")
        raw = canonical(report) + b"\n"
        if len(raw) > MAX_REPORT_BYTES:
            raise StoreFull("Report exceeds 8 MiB")
        target = self._path(report["artifact_id"])
        with self._locked():
            total, count = self._usage()
            # Repeated identical runs are idempotent, including a full store.
            # Existing corrupt data is an explicit error, never silently replaced.
            try:
                existing = self.get(report["artifact_id"])
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing != report:
                    raise ValueError("Existing report does not match")
                return
            if total + len(raw) > self.max_bytes or count + 1 > self.max_files:
                raise StoreFull(
                    "Artifact store quota exceeded; export or remove reports locally"
                )
            descriptor, name = tempfile.mkstemp(
                prefix=".report-", suffix=".tmp", dir=self.root
            )
            try:
                with os.fdopen(descriptor, "wb") as destination:
                    destination.write(raw)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.replace(name, target)
            finally:
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass

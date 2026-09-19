"""Shared POSIX export-budget v1 protocol, vendored identically in engine and CLI.

Only cooperating writers using one private state directory share the budget.
Completed reports are never deleted automatically. Reservations precede output
creation and remain charged after abrupt death, including across rename.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 128
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_LEDGER_BYTES = 256 * 1024


class ExportBudgetError(OSError):
    pass


def identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode]


def regular(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ExportBudgetError("Tracked export must be a regular, singly linked file")
    return info


def matches(path, size, expected):
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return False
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != size:
            return False
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            data = source.read(MAX_REPORT_BYTES + 1)
        return len(data) == size and hashlib.sha256(data).hexdigest() == expected
    finally:
        os.close(descriptor)


class ExportBudget:
    def __init__(self, root=None, *, max_bytes=MAX_BYTES, max_files=MAX_FILES):
        if os.name != "posix":
            raise ExportBudgetError("Bounded report exports require POSIX file locking")
        if (
            type(max_bytes) is not int
            or type(max_files) is not int
            or not 0 < max_bytes <= MAX_BYTES
            or not 0 < max_files <= MAX_FILES
        ):
            raise ValueError(
                "Export budget limits must be positive and cannot exceed defaults"
            )
        self.root = Path(
            root
            or os.getenv("ENTROTTER_EXPORT_STATE_DIR")
            or Path.home() / ".local/state/entrotter/export-budget-v1"
        ).absolute()
        self.max_bytes, self.max_files = max_bytes, max_files
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ExportBudgetError(
                "Export state must be a private directory owned by this user"
            )
        self.root = self.root.resolve()

    @staticmethod
    def _private(info):
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ExportBudgetError("Invalid private export bookkeeping file")

    @contextmanager
    def _locked(self):
        import fcntl

        descriptor = os.open(
            self.root / ".lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            info = os.fstat(descriptor)
            self._private(info)
            if info.st_size:
                raise ExportBudgetError("Invalid export lock contents")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ExportBudgetError(
                    "Export budget is busy; no report was written"
                ) from None
            yield
        finally:
            os.close(descriptor)

    def _read(self):
        try:
            descriptor = os.open(
                self.root / "ledger.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
        except FileNotFoundError:
            return []
        with os.fdopen(descriptor, "rb") as source:
            self._private(os.fstat(source.fileno()))
            data = source.read(MAX_LEDGER_BYTES + 1)
        if len(data) > MAX_LEDGER_BYTES:
            raise ExportBudgetError("Export ledger exceeds its metadata limit")
        try:
            value = json.loads(data)
            entries = value["entries"]
            if (
                type(value["version"]) is not int
                or value["version"] != 1
                or not isinstance(entries, list)
                or len(entries) > MAX_FILES
            ):
                raise ValueError("Invalid ledger version/entries")
            paths = set()
            for entry in entries:
                path = entry["path"]
                if (
                    not isinstance(path, str)
                    or not Path(path).is_absolute()
                    or path in paths
                ):
                    raise ValueError("Invalid or duplicate export path")
                paths.add(path)
                if entry["kind"] == "pending":
                    if (
                        type(entry["bytes"]) is not int
                        or not 0 < entry["bytes"] <= MAX_REPORT_BYTES
                        or not isinstance(entry["target"], str)
                        or not Path(entry["target"]).is_absolute()
                        or not isinstance(entry["sha256"], str)
                        or len(entry["sha256"]) != 64
                        or (
                            entry["prior"] is not None
                            and (
                                not isinstance(entry["prior"], list)
                                or len(entry["prior"]) != 5
                                or any(type(x) is not int for x in entry["prior"])
                            )
                        )
                    ):
                        raise ValueError("Invalid pending reservation")
                elif entry["kind"] != "saved":
                    raise ValueError("Unknown export record")
            return entries
        except (ValueError, KeyError, TypeError) as error:
            raise ExportBudgetError(
                "Invalid export ledger; inspect bookkeeping before writing"
            ) from error

    def _save(self, entries):
        data = (
            json.dumps({"version": 1, "entries": entries}, sort_keys=True) + "\n"
        ).encode()
        if len(data) > MAX_LEDGER_BYTES:
            raise ExportBudgetError("Export ledger metadata limit reached")
        temporary = self.root / ".ledger-next"
        # This reserved internal file can be left by a killed metadata writer.
        # Holding the shared lock proves no cooperating writer still owns it.
        if temporary.exists() or temporary.is_symlink():
            self._private(temporary.lstat())
            temporary.unlink()
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.root / "ledger.json")
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _refresh(self, entries):
        saved = {}
        pending = []
        for entry in entries:
            if entry["kind"] == "saved" and regular(Path(entry["path"])) is not None:
                saved[entry["path"]] = entry
        for entry in entries:
            if entry["kind"] != "pending":
                continue
            temporary, target = Path(entry["path"]), Path(entry["target"])
            if regular(temporary) is not None:
                pending.append(entry)
            elif matches(target, entry["bytes"], entry["sha256"]):
                saved[str(target)] = {"kind": "saved", "path": str(target)}
            elif identity(target) is None or identity(target) == entry["prior"]:
                # No temporary exists and publication never happened, or the
                # operator removed it. No output bytes remain to charge.
                continue
            else:
                # An uncertain post-crash publication stays conservatively charged.
                pending.append(entry)
        return [*saved.values(), *pending]

    def _usage(self, entries, *, enforce=True):
        total = 0
        saved_paths = {e["path"] for e in entries if e["kind"] == "saved"}
        for entry in entries:
            info = regular(Path(entry["path"]))
            size = info.st_size if info is not None else 0
            if (
                entry["kind"] == "pending"
                and info is None
                and entry["target"] not in saved_paths
            ):
                target = regular(Path(entry["target"]))
                size = max(size, target.st_size if target is not None else 0)
            total += max(size, entry["bytes"]) if entry["kind"] == "pending" else size
        if enforce and (total > self.max_bytes or len(entries) > self.max_files):
            raise ExportBudgetError(
                "Export budget already exceeded; remove tracked reports locally"
            )
        return total, len(entries)

    def snapshot(self):
        with self._locked():
            entries = self._refresh(self._read())
            total, count = self._usage(entries, enforce=False)
            return {
                "state_directory": str(self.root),
                "used_bytes": total,
                "retained_files": count,
                "max_bytes": self.max_bytes,
                "max_files": self.max_files,
                "within_budget": total <= self.max_bytes and count <= self.max_files,
                "entries": [
                    {
                        "status": "incomplete"
                        if entry["kind"] == "pending"
                        else "complete",
                        "path": entry["path"],
                        **(
                            {
                                "destination": entry["target"],
                                "reserved_bytes": entry["bytes"],
                            }
                            if entry["kind"] == "pending"
                            else {}
                        ),
                    }
                    for entry in entries
                ],
                "cleanup": "Remove unwanted reports or listed incomplete temporary files locally; never reset the ledger to free capacity",
            }

    def write(self, raw, path):
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_REPORT_BYTES:
            raise ValueError("Report export exceeds 8 MiB or is empty")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = path.parent.resolve() / path.name
        if path.is_relative_to(self.root):
            raise ExportBudgetError("Reports cannot replace export bookkeeping")
        expected = hashlib.sha256(raw).hexdigest()
        with self._locked():
            entries = self._refresh(self._read())
            total, count = self._usage(entries)
            if any(e["kind"] == "pending" and e["path"] == str(path) for e in entries):
                raise ExportBudgetError(
                    "Destination is reserved by an incomplete export"
                )
            if any(
                e["kind"] == "saved" and e["path"] == str(path) for e in entries
            ) and matches(path, len(raw), expected):
                return  # Identical tracked exports need no additional allocation.
            if total + len(raw) > self.max_bytes or count + 1 > self.max_files:
                raise ExportBudgetError(
                    "Export budget full (128 MiB/128 files); use the exports command to inspect tracked paths"
                )
            temporary = path.parent / (".report-" + uuid.uuid4().hex + ".tmp")
            reservation = {
                "kind": "pending",
                "path": str(temporary),
                "target": str(path),
                "bytes": len(raw),
                "sha256": expected,
                "prior": identity(path),
            }
            # Durably reserve peak old+new bytes before the first output file is created.
            self._save([*entries, reservation])
            descriptor = None
            created = None
            try:
                descriptor = os.open(
                    temporary,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o600,
                )
                created = os.fstat(descriptor)
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = None
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
                # The durable reservation intentionally survives publication.
                # Next admission recognizes the exact bytes at the final path;
                # no post-publication ledger failure can untrack this output.
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if created is not None:
                    try:
                        current = temporary.lstat()
                        if (current.st_dev, current.st_ino) == (
                            created.st_dev,
                            created.st_ino,
                        ):
                            temporary.unlink()
                    except FileNotFoundError:
                        pass

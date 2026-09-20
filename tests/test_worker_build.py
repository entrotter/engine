"""Build input bounds; daemon access is replaced only in these unit tests."""

from contextlib import nullcontext
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_worker", ROOT / "scripts/build_worker.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class WorkerBuildTests(unittest.TestCase):
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

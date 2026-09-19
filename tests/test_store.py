import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from entrotter_engine.artifact import canonical, seal
from entrotter_engine.store import ArtifactStore, MAX_REPORT_BYTES, MAX_STORE_BYTES, StoreBusy, StoreFull


def competing_writer(root, number, barrier, queue):
    barrier.wait(timeout=10)
    try:
        ArtifactStore(root, max_files=1).put(seal({'schema_version': '0.1.0', 'writer': number}))
        queue.put('saved')
    except (StoreBusy, StoreFull):
        queue.put('rejected')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report = seal({'schema_version': '0.1.0', 'example': 1})
        self.other = seal({'schema_version': '0.1.0', 'example': 2})

    def test_count_budget_and_full_store_idempotence(self):
        store = ArtifactStore(self.root, max_files=1)
        store.put(self.report)
        with self.assertRaises(StoreFull):
            store.put(self.other)
        store.put(self.report)
        self.assertEqual(store.get(self.report['artifact_id']), self.report)
        self.assertEqual(len(list(self.root.glob('*.json'))), 1)

    def test_exact_byte_budget_and_no_temporary_overrun(self):
        size = len(canonical(self.report)) + 1
        store = ArtifactStore(self.root, max_bytes=size)
        store.put(self.report)
        with self.assertRaises(StoreFull):
            store.put(self.other)
        self.assertEqual(sum(p.stat().st_size for p in self.root.iterdir()), size)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_default_128_mib_budget_counts_existing_and_crash_files(self):
        store = ArtifactStore(self.root)
        with (self.root / '.report-crashed.tmp').open('wb') as f:
            f.truncate(MAX_STORE_BYTES)
        with self.assertRaises(StoreFull):
            store.put(self.report)
        self.assertFalse(list(self.root.glob('*.json')))
        self.assertEqual((self.root / '.report-crashed.tmp').stat().st_size, MAX_STORE_BYTES)

    def test_default_file_budget_counts_unrelated_files(self):
        store = ArtifactStore(self.root)
        for i in range(128):
            (self.root / f'unrelated-{i}').touch()
        with self.assertRaises(StoreFull):
            store.put(self.report)
        self.assertEqual(len(list(self.root.iterdir())), 129)  # Includes zero-byte lock.

    def test_oversized_report_and_read_are_rejected(self):
        store = ArtifactStore(self.root)
        report = seal({'schema_version': '0.1.0', 'large': 'x' * MAX_REPORT_BYTES})
        with self.assertRaises(StoreFull):
            store.put(report)
        target = self.root / (self.report['artifact_id'] + '.json')
        with target.open('wb') as f:
            f.truncate(MAX_REPORT_BYTES + 1)
        with self.assertRaises(ValueError):
            store.get(self.report['artifact_id'])

    def test_symlink_fifo_and_hash_mismatch_are_rejected(self):
        store = ArtifactStore(self.root)
        target = self.root / (self.report['artifact_id'] + '.json')
        with tempfile.TemporaryDirectory() as outside:
            victim = Path(outside) / 'private.json'
            victim.write_bytes(canonical(self.report))
            target.symlink_to(victim)
            with self.assertRaises(OSError):
                store.get(self.report['artifact_id'])
            with self.assertRaises(OSError):
                store.put(self.report)
            self.assertEqual(victim.read_bytes(), canonical(self.report))
            target.unlink()
        os.mkfifo(target)
        with self.assertRaises(ValueError):
            store.get(self.report['artifact_id'])
        target.unlink()
        target.write_bytes(canonical(self.other))
        with self.assertRaises(ValueError):
            store.get(self.report['artifact_id'])

    def test_failed_atomic_replace_leaves_no_partial_artifact(self):
        store = ArtifactStore(self.root)
        with patch('entrotter_engine.store.os.replace', side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):
                store.put(self.report)
        self.assertEqual([p.name for p in self.root.iterdir()], ['.store.lock'])
        store.put(self.report)
        self.assertEqual(store.get(self.report['artifact_id']), self.report)

    def test_two_real_processes_cannot_overrun_one_file_budget(self):
        ArtifactStore(self.root, max_files=1)
        context = multiprocessing.get_context('spawn')
        barrier, queue = context.Barrier(3), context.Queue()
        children = [context.Process(target=competing_writer, args=(str(self.root), i, barrier, queue)) for i in range(2)]
        try:
            for child in children:
                child.start()
            barrier.wait(timeout=10)
            results = [queue.get(timeout=10) for _ in children]
            for child in children:
                child.join(timeout=10)
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(sorted(results), ['rejected', 'saved'])
            self.assertEqual(len(list(self.root.glob('*.json'))), 1)
        finally:
            for child in children:
                if child.is_alive():
                    child.kill()
                    child.join(timeout=5)
            queue.close()
            queue.join_thread()


if __name__ == '__main__':
    unittest.main()

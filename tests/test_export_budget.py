"""Real filesystem/process checks for shared export retention; fault hooks labelled."""
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = 'entrotter_engine.export_budget'
exports = importlib.import_module(MODULE)


class ExportBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / 'state'
        self.output = self.root / 'reports'
        self.output.mkdir()

    def budget(self, size=20, files=3):
        return exports.ExportBudget(self.state, max_bytes=size, max_files=files)

    def test_aggregate_bytes_across_directories_and_replacement_peak(self):
        budget = self.budget(size=10)
        first = self.output / 'one.json'; second = self.root / 'elsewhere/two.json'
        budget.write(b'123456', first)
        with self.assertRaisesRegex(OSError, 'budget full'): budget.write(b'12345', second)
        with self.assertRaisesRegex(OSError, 'budget full'): budget.write(b'abcdef', first)
        self.assertEqual(first.read_bytes(), b'123456'); self.assertFalse(second.exists())
        budget.write(b'123456', first)  # Same complete tracked output needs no new bytes.
        first.unlink(); budget.write(b'abcdef', second)
        self.assertEqual(second.read_bytes(), b'abcdef')

    def test_inspection_lists_paths_and_over_budget_modified_content(self):
        budget = self.budget(size=10)
        target = self.output / 'one'; budget.write(b'123456', target)
        status = budget.snapshot()
        self.assertEqual(status['used_bytes'], 6)
        self.assertEqual(status['retained_files'], 1)
        self.assertEqual(status['entries'][0]['path'], str(target.resolve()))
        target.write_bytes(b'x' * 11)
        status = budget.snapshot()
        self.assertEqual(status['used_bytes'], 11)
        self.assertFalse(status['within_budget'])
        with self.assertRaises(OSError): budget.write(b'1', self.output / 'two')

    def test_file_count_and_manual_deletion_release_capacity(self):
        budget = self.budget(files=2)
        first, second, third = [self.output / f'{i}.json' for i in range(3)]
        budget.write(b'a', first); budget.write(b'b', second)
        with self.assertRaisesRegex(OSError, 'budget full'): budget.write(b'c', third)
        self.assertEqual(first.read_bytes(), b'a'); self.assertEqual(second.read_bytes(), b'b')
        first.unlink(); budget.write(b'c', third)
        self.assertEqual(third.read_bytes(), b'c')

    def test_production_byte_limit_rejects_seventeenth_eight_mib_export(self):
        budget = exports.ExportBudget(self.state)
        raw = b'x' * (8 * 1024 * 1024)
        for i in range(16): budget.write(raw, self.output / str(i))
        with self.assertRaisesRegex(OSError, 'budget full'): budget.write(raw, self.output / '17')
        self.assertEqual(sum(p.stat().st_size for p in self.output.iterdir()), 128 * 1024 * 1024)
        budget.write(raw, self.output / '0')
        self.assertEqual(len(list(self.output.iterdir())), 16)

    def test_default_count_rejects_129th_completed_export(self):
        budget = exports.ExportBudget(self.state)
        for i in range(128): budget.write(b'x', self.output / f'{i}.json')
        with self.assertRaisesRegex(OSError, 'budget full'): budget.write(b'x', self.output / '129.json')
        self.assertEqual(len(list(self.output.iterdir())), 128)

    def test_changed_tracked_files_and_hard_links_cannot_hide_usage(self):
        budget = self.budget(size=10)
        first = self.output / 'one'; budget.write(b'123456', first)
        budget.write(b'1', self.output / 'two')  # Reconcile the first published reservation.
        first.write_bytes(b'x' * 11)
        with self.assertRaisesRegex(OSError, 'already exceeded'): budget.write(b'1', self.output / 'three')
        first.write_bytes(b'x'); os.link(first, self.output / 'alias')
        with self.assertRaisesRegex(OSError, 'singly linked'): budget.write(b'1', self.output / 'three')

    def test_parent_alias_does_not_double_charge_same_export(self):
        budget = self.budget(size=6, files=1); alias = self.root / 'alias'; alias.symlink_to(self.output, target_is_directory=True)
        budget.write(b'123456', self.output / 'one'); budget.write(b'123456', alias / 'one')
        self.assertEqual((self.output / 'one').read_bytes(), b'123456')

    def test_destination_symlink_is_replaced_without_modifying_referent(self):
        budget = self.budget(); other = self.root / 'other'; other.write_bytes(b'private')
        target = self.output / 'report'; target.symlink_to(other)
        budget.write(b'new', target)
        self.assertFalse(target.is_symlink()); self.assertEqual(other.read_bytes(), b'private')
        self.assertEqual(target.read_bytes(), b'new')

    def test_failed_publish_preserves_previous_and_releases_reservation(self):
        budget = self.budget(size=10); target = self.output / 'report'; target.write_bytes(b'old')
        replace = os.replace
        def fail_report(source, destination):
            if Path(source).name.startswith('.report-'): raise OSError('injected publish failure')
            return replace(source, destination)
        with patch.object(exports.os, 'replace', side_effect=fail_report), self.assertRaises(OSError):
            budget.write(b'123456', target)
        self.assertEqual(target.read_bytes(), b'old'); self.assertEqual(list(self.output.iterdir()), [target])
        budget.write(b'123456', target); self.assertEqual(target.read_bytes(), b'123456')

    def test_reservation_failure_writes_no_output_bytes(self):
        budget = self.budget(); target = self.output / 'report'
        with patch.object(exports.os, 'fsync', side_effect=OSError('injected metadata failure')), self.assertRaises(OSError):
            budget.write(b'payload', target)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_or_oversized_bookkeeping_fails_closed(self):
        budget = self.budget(); ledger = self.state / 'ledger.json'
        for data in [b'[]', b'{"version":2,"entries":[]}', b'{"version":true,"entries":[]}',
                     b'{"version":1,"entries":[{"kind":"saved","path":"relative"}]}', b'x' * (256 * 1024 + 1)]:
            ledger.write_bytes(data); ledger.chmod(0o600)
            with self.subTest(data=data[:50]), self.assertRaises(OSError): budget.write(b'x', self.output / 'new')
            self.assertFalse((self.output / 'new').exists())

    def test_private_state_and_reserved_files_are_required(self):
        self.state.mkdir(mode=0o755)
        with self.assertRaisesRegex(OSError, 'private directory'): self.budget()
        self.state.chmod(0o700); budget = self.budget()
        with self.assertRaisesRegex(OSError, 'bookkeeping'): budget.write(b'x', self.state / 'ledger.json')
        unrelated = self.root / 'unrelated'; unrelated.write_bytes(b'keep')
        (self.state / 'ledger.json').symlink_to(unrelated)
        with self.assertRaises(OSError): budget.write(b'x', self.output / 'new')
        self.assertEqual(unrelated.read_bytes(), b'keep')

    def test_two_real_processes_cannot_overrun_shared_budget(self):
        code = '''import importlib,sys
from pathlib import Path
m=importlib.import_module(sys.argv[1]); budget=m.ExportBudget(Path(sys.argv[2]),max_bytes=10,max_files=3)
sys.stdin.buffer.read(1)
try: budget.write(b'123456',Path(sys.argv[3]))
except OSError: raise SystemExit(1)
'''
        children = [subprocess.Popen([sys.executable, '-c', code, MODULE, str(self.state), str(self.output / str(i))],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
        for child in children: child.stdin.write(b'x'); child.stdin.flush()
        results = [child.communicate(timeout=10) for child in children]
        self.assertEqual(sorted(child.returncode for child in children), [0, 1], results)
        self.assertEqual(sum(p.stat().st_size for p in self.output.iterdir()), 6)
        with self.assertRaises(OSError): self.budget(size=10).write(b'123456', self.output / 'third')

    def crash_at_publish(self, after):
        target = self.output / 'report'; target.write_bytes(b'old')
        code = '''import importlib,os,sys,time
from pathlib import Path
m=importlib.import_module(sys.argv[1]); replace=os.replace

def pause(source,destination):
    if Path(source).name.startswith('.report-'):
        if sys.argv[4]=='after': replace(source,destination)
        print('ready',flush=True)
        time.sleep(30)
    else: replace(source,destination)
m.os.replace=pause
m.ExportBudget(Path(sys.argv[2]),max_bytes=10,max_files=3).write(b'123456',Path(sys.argv[3]))
'''
        child = subprocess.Popen([sys.executable, '-c', code, MODULE, str(self.state), str(target), 'after' if after else 'before'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import select
            ready, _, _ = select.select([child.stdout], [], [], 10)
            self.assertTrue(ready, 'Child did not reach the real publication boundary')
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            child.send_signal(signal.SIGKILL); child.communicate(timeout=5)
            self.assertEqual(child.returncode, -signal.SIGKILL)
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=5)
        return target

    def test_sigkill_before_rename_keeps_temporary_bytes_charged(self):
        target = self.crash_at_publish(False)
        self.assertEqual(target.read_bytes(), b'old')
        temporary = list(self.output.glob('.report-*.tmp')); self.assertEqual(len(temporary), 1)
        self.assertEqual(temporary[0].stat().st_size, 6)
        with self.assertRaisesRegex(OSError, 'budget full'): self.budget(size=10).write(b'123456', self.output / 'other')
        temporary[0].unlink()  # Explicit operator cleanup of the owned test file.
        self.budget(size=10).write(b'123456', self.output / 'other')
        self.assertEqual(target.read_bytes(), b'old')

    def test_sigkill_after_rename_recovers_exact_published_output(self):
        target = self.crash_at_publish(True)
        self.assertEqual(target.read_bytes(), b'123456')
        self.assertEqual(list(self.output.glob('.report-*.tmp')), [])
        with self.assertRaisesRegex(OSError, 'budget full'): self.budget(size=10).write(b'123456', self.output / 'other')
        self.budget(size=10).write(b'123456', target)


if __name__ == '__main__': unittest.main()

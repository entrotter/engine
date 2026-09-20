import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from entrotter_engine.artifact import MAX_REPORT_BYTES, seal, write_report


class ArtifactWriteTests(unittest.TestCase):
    def test_oversized_export_does_not_replace_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            original = seal({'schema_version': '0.1.0', 'example': 1})
            write_report(original, path)
            before = path.read_bytes()
            huge = seal({'schema_version': '0.1.0', 'large': 'x' * MAX_REPORT_BYTES})
            with self.assertRaisesRegex(ValueError, '8 MiB'):
                write_report(huge, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['report.json'])

    def test_predictable_temp_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / 'unrelated.txt'
            victim.write_text('preserve me')
            path = root / 'report.json'
            path.with_name('report.json.tmp').symlink_to(victim)
            report = seal({'schema_version': '0.1.0', 'example': 1})
            write_report(report, path)
            self.assertEqual(json.loads(path.read_bytes()), report)
            self.assertEqual(victim.read_text(), 'preserve me')

    def test_disk_failure_preserves_previous_report_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            original = seal({'schema_version': '0.1.0', 'example': 1})
            write_report(original, path)
            replace = os.replace
            def fail_report(source, destination):
                if Path(source).name.startswith('.report-'):
                    raise OSError('injected disk failure')
                return replace(source, destination)
            with patch('entrotter_engine.export_budget.os.replace', side_effect=fail_report):
                with self.assertRaises(OSError):
                    write_report(seal({'schema_version': '0.1.0', 'example': 2}), path)
            self.assertEqual(json.loads(path.read_bytes()), original)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['report.json'])


if __name__ == '__main__':
    unittest.main()

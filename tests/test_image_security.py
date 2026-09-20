"""Negative policy fixtures; real image/package/signature scans run separately."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_security', ROOT / 'scripts/check_image_security.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
IMAGE = 'sha256:' + 'a' * 64


class ImageSecurityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 19, 20, tzinfo=timezone.utc)
        self.database = {'Version': 2, 'UpdatedAt': (self.now - timedelta(hours=1)).isoformat(),
                         'NextUpdate': (self.now + timedelta(hours=1)).isoformat()}
        self.report = {
            'SchemaVersion': 2, 'Trivy': {'Version': audit.TRIVY_VERSION},
            'ArtifactType': 'container_image',
            'Metadata': {'ImageID': IMAGE, 'OS': {'Family': 'wolfi'}},
            'Results': [{'Class': 'os-pkgs', 'Type': 'wolfi',
                         'Packages': [{'Name': name, 'Version': 'fixture-version'} for name in
                                      ['python-3.14', 'python-3.14-base', 'glibc-2.44', 'libssl3', 'ca-certificates-bundle']]}]}

    def evaluate(self, report=None, database=None):
        return audit.evaluate(self.report if report is None else report, IMAGE,
                              self.database if database is None else database, self.now)

    def test_complete_matching_inventory_with_current_database_passes(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['vulnerability_count'], 0)
        self.assertEqual(result['inventories'][0]['packages'], 5)

    def test_every_finding_fails_including_low_unknown_and_unfixed(self):
        for severity in ['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
            for fixed in ['', 'newer-version']:
                with self.subTest(severity=severity, fixed=fixed):
                    changed = deepcopy(self.report)
                    changed['Results'][0]['Vulnerabilities'] = [
                        {'VulnerabilityID': 'CVE-test-fixture', 'PkgName': 'python-3.14',
                         'Severity': severity, 'FixedVersion': fixed}]
                    result = self.evaluate(changed)
                    self.assertEqual(result['status'], 'findings')
                    self.assertEqual(result['vulnerability_count'], 1)

    def test_wrong_image_type_scanner_or_schema_fails(self):
        variants = []
        for field, value in [('SchemaVersion', 1), ('ArtifactType', 'filesystem'),
                             ('Trivy', {'Version': 'different'})]:
            changed = deepcopy(self.report); changed[field] = value; variants.append(changed)
        changed = deepcopy(self.report); changed['Metadata']['ImageID'] = 'sha256:' + 'b' * 64; variants.append(changed)
        for report in variants:
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.evaluate(report)

    def test_empty_partial_or_unsupported_os_coverage_fails(self):
        variants = []
        changed = deepcopy(self.report); changed['Results'] = []; variants.append(changed)
        changed = deepcopy(self.report); changed['Results'][0]['Packages'] = []; variants.append(changed)
        changed = deepcopy(self.report); changed['Results'][0]['Packages'].pop(); variants.append(changed)
        changed = deepcopy(self.report); changed['Results'][0]['Class'] = 'lang-pkgs'; variants.append(changed)
        changed = deepcopy(self.report); changed['Metadata']['OS']['Family'] = 'unknown'; variants.append(changed)
        changed = deepcopy(self.report); changed['Metadata']['OS']['Eosl'] = True; variants.append(changed)
        for report in variants:
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.evaluate(report)

    def test_stale_future_expired_or_unversioned_database_fails(self):
        variants = [dict(self.database, Version=1),
                    dict(self.database, UpdatedAt=(self.now - timedelta(days=2)).isoformat()),
                    dict(self.database, UpdatedAt=(self.now + timedelta(hours=1)).isoformat()),
                    dict(self.database, NextUpdate=(self.now - timedelta(seconds=1)).isoformat()),
                    dict(self.database, UpdatedAt='2026-09-19T19:00:00')]
        for database in variants:
            with self.subTest(database=database), self.assertRaises(ValueError):
                self.evaluate(database=database)

    def test_malformed_inventory_cannot_be_a_zero_finding_success(self):
        for key, value in [('Packages', {}), ('Vulnerabilities', {}),
                           ('Packages', [{'Name': 'python-3.14'}]),
                           ('Vulnerabilities', [{'PkgName': 'python-3.14'}])]:
            changed = deepcopy(self.report); changed['Results'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evaluate(changed)

    def test_modified_tool_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); supplied = root / 'download'; supplied.write_bytes(b'modified release')
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                audit.verified_download('unused', hashlib.sha256(b'expected release').hexdigest(),
                                        root / 'target', supplied)


if __name__ == '__main__':
    unittest.main()

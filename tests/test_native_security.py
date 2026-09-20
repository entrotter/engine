"""Policy fixtures; real signatures and full upstream scans run separately."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('native_security', ROOT / 'scripts/check_native_security.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class NativeSecurityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 19, 20, tzinfo=timezone.utc)
        self.database = {'Version': 2, 'UpdatedAt': (self.now - timedelta(hours=1)).isoformat(),
                         'NextUpdate': (self.now + timedelta(hours=1)).isoformat()}
        names = ['rustls', 'revm', 'tokio'] + [f'fixture-{i}' for i in range(1123)]
        self.sbom = {'spdxVersion': 'SPDX-2.3', 'packages': [
            {'name': name, 'versionInfo': '1.0.0', 'externalRefs': [
                {'referenceType': 'purl', 'referenceLocator': f'pkg:cargo/{name}@1.0.0'}]} for name in names]}
        self.sbom['packages'].append({'name': 'anvil', 'versionInfo': audit.VERSION})
        self.report = {'SchemaVersion': 2, 'Trivy': {'Version': audit.TRIVY_VERSION},
                       'ArtifactType': 'spdx', 'Results': [{'Class': 'lang-pkgs', 'Type': 'cargo',
                       'Packages': [{'Name': name, 'Version': '1.0.0',
                                     'Identifier': {'PURL': f'pkg:cargo/{name}@1.0.0'}} for name in names]}]}
        self.manifest = {'architecture': 'arm64', 'foundry_version': audit.VERSION,
                         'foundry_archive_sha256': audit.RELEASES['arm64']['archive'],
                         'anvil_binary_sha256': 'a' * 64}
        subject = [{'name': f'foundry_v{audit.VERSION}_linux_arm64.tar.gz',
                    'digest': {'sha256': self.manifest['foundry_archive_sha256']}}]
        self.provenance = {'predicateType': audit.PROVENANCE, 'subject': subject + [
            {'name': 'anvil', 'digest': {'sha256': self.manifest['anvil_binary_sha256']}}],
            'predicate': {'buildDefinition': {'resolvedDependencies': [
                {'digest': {'gitCommit': audit.COMMIT},
                 'uri': f'git+https://github.com/foundry-rs/foundry@refs/tags/v{audit.VERSION}'}]}}}
        self.signed = {'predicateType': audit.SPDX, 'subject': subject, 'predicate': deepcopy(self.sbom)}

    def evaluate(self, report=None, database=None):
        return audit.evaluate(self.sbom, self.report if report is None else report,
                              self.database if database is None else database, self.now)

    def test_complete_inventory_passes_and_lists_non_cargo_scope(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['cargo_packages'], 1126)
        self.assertEqual([p['name'] for p in result['outside_cargo_inventory']], ['anvil'])
        audit.verify_claims(self.provenance, self.signed, self.sbom, self.manifest)

    def test_missing_duplicate_wrong_version_or_replaced_package_fails(self):
        for change in ['missing', 'duplicate', 'version', 'purl', 'type']:
            report = deepcopy(self.report); result = report['Results'][0]
            if change == 'missing': result['Packages'].pop()
            elif change == 'duplicate': result['Packages'].append(result['Packages'][0])
            elif change == 'version': result['Packages'][0]['Version'] = '2.0.0'
            elif change == 'purl': result['Packages'][0]['Identifier']['PURL'] = 'pkg:cargo/other@1.0.0'
            else: result['Type'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError): self.evaluate(report)

    def test_every_severity_and_unfixed_finding_fails(self):
        for severity in ['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
            report = deepcopy(self.report); report['Results'][0]['Vulnerabilities'] = [
                {'VulnerabilityID': 'RUSTSEC-fixture', 'PkgName': 'rustls', 'Severity': severity, 'FixedVersion': ''}]
            with self.subTest(severity=severity):
                self.assertEqual(self.evaluate(report)['status'], 'findings')

    def test_empty_report_wrong_schema_or_scanner_fails(self):
        for field, value in [('Results', []), ('ArtifactType', 'container_image'), ('SchemaVersion', 1),
                             ('Trivy', {'Version': 'untrusted'})]:
            report = deepcopy(self.report); report[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.evaluate(report)

    def test_stale_future_naive_or_expired_database_fails(self):
        for database in [dict(self.database, UpdatedAt=(self.now - timedelta(days=2)).isoformat()),
                         dict(self.database, UpdatedAt=(self.now + timedelta(hours=1)).isoformat()),
                         dict(self.database, UpdatedAt='2026-09-19T19:00:00'),
                         dict(self.database, NextUpdate=self.now.isoformat()), dict(self.database, Version=1)]:
            with self.subTest(database=database), self.assertRaises(ValueError): self.evaluate(database=database)

    def test_changed_binary_archive_commit_or_signed_inventory_fails(self):
        for change in ['binary', 'archive', 'commit', 'sbom', 'predicate', 'version']:
            provenance, signed, manifest = deepcopy(self.provenance), deepcopy(self.signed), deepcopy(self.manifest)
            if change == 'binary': manifest['anvil_binary_sha256'] = 'b' * 64
            elif change == 'archive': signed['subject'][0]['digest']['sha256'] = 'c' * 64
            elif change == 'commit': provenance['predicate']['buildDefinition']['resolvedDependencies'][0]['digest']['gitCommit'] = 'd' * 40
            elif change == 'sbom': signed['predicate']['packages'][0]['versionInfo'] = 'changed'
            elif change == 'predicate': signed['predicateType'] = 'unsigned-type'
            else: manifest['foundry_version'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit.verify_claims(provenance, signed, self.sbom, manifest)

    def test_payload_type_schema_and_base64_are_checked(self):
        bundle = {'dsseEnvelope': {'payloadType': 'application/vnd.in-toto+json',
                  'payload': base64.b64encode(json.dumps({'_type': 'https://in-toto.io/Statement/v1'}).encode()).decode()}}
        self.assertEqual(audit.statement(bundle)['_type'], 'https://in-toto.io/Statement/v1')
        for key, value in [('payloadType', 'other'), ('payload', '%%%'),
                           ('payload', base64.b64encode(b'{"_type":"other"}').decode())]:
            changed = deepcopy(bundle); changed['dsseEnvelope'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): audit.statement(changed)


if __name__ == '__main__':
    unittest.main()

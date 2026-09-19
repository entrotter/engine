"""Failure-path tests for the CI policies; scanner results are explicitly fixtures."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


security = load('check_security')
dependencies = load('check_dependency_manifest')


class QualityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.finding = dict(filename='src/example.py', test_id='B603', line_number=3, code='3 example()\n')
        self.report = {'errors': [], 'metrics': {'_totals': {'loc': 1, 'skipped_tests': 0}}, 'results': [self.finding]}
        self.reviews = {'findings': [{**security.fingerprint(self.finding), 'reason': 'A specific reviewed rationale explaining this expected fixed call.'}]}
        self.project = {'project': {'dependencies': []}, 'build-system': {'requires': ['setuptools==84.0.0']}}
        self.lock = 'setuptools==84.0.0 \\\n --hash=sha256:example\n'

    def test_only_exact_reviewed_findings_pass(self):
        self.assertEqual(security.evaluate(self.report, self.reviews), 1)
        for key, value in [('line_number', 4), ('code', '3 different()\n'), ('test_id', 'B602')]:
            changed = deepcopy(self.report)
            changed['results'][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                security.evaluate(changed, self.reviews)

    def test_new_or_disappeared_findings_fail(self):
        for results in [[], [self.finding, self.finding]]:
            with self.subTest(results=results), self.assertRaises(ValueError):
                security.evaluate({**self.report, 'results': results}, self.reviews)

    def test_empty_partial_or_failed_scans_fail(self):
        for report in [{**self.report, 'errors': ['failed source']},
                       {**self.report, 'metrics': {'_totals': {'loc': 0}}},
                       {**self.report, 'metrics': {'_totals': {'loc': 1, 'skipped_tests': 1}}}]:
            with self.subTest(report=report), self.assertRaises(ValueError):
                security.evaluate(report, self.reviews)

    def test_missing_review_reason_fails(self):
        self.reviews['findings'][0]['reason'] = ''
        with self.assertRaises(ValueError):
            security.evaluate(self.report, self.reviews)

    def test_build_and_runtime_dependencies_must_be_in_lock(self):
        self.assertEqual(dependencies.check(self.project, self.lock)['audited_locked_packages'], 1)
        for requirement in ['unexpected==1.0', 'setuptools>=84', 'setuptools==83.0.0', 'setuptools==84.0.0; python_version>="3.11"']:
            self.project['project']['dependencies'] = [requirement]
            with self.subTest(requirement=requirement), self.assertRaises(ValueError):
                dependencies.check(self.project, self.lock)

    def test_locked_extras_are_counted_as_audited_packages(self):
        locked = self.lock + 'cachecontrol[filecache]==0.14.4 \\\n --hash=sha256:example\n'
        self.assertEqual(dependencies.check(self.project, locked)['audited_locked_packages'], 2)

    def test_optional_runtime_dependencies_are_not_missed(self):
        self.project['project']['optional-dependencies'] = {'feature': ['unexpected==1.0']}
        with self.assertRaises(ValueError):
            dependencies.check(self.project, self.lock)


if __name__ == '__main__':
    unittest.main()

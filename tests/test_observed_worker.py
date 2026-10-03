"""Closed observed-job binding and timer probes; mocks do not prove isolation."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from entrotter_engine import consumer_observations as views
from entrotter_engine.__main__ import main
from entrotter_engine.artifact import canonical, seal
from entrotter_engine.evm import ExecutionError
from entrotter_engine.worker_protocol import encode_observed_trace_request, execute_request
from test_consumer_observations import sample_wrapper
import test_isolated as harness


class ObservedWorkerProtocolTests(unittest.TestCase):
    def test_each_worker_requests_builtin_seccomp_independently_of_daemon_default(self):
        from entrotter_engine.isolated import worker_args

        for fork in (False, True):
            args = worker_args(['docker'], 'sha256:' + 'a' * 64, 'owned', fork=fork)
            self.assertIn('--security-opt=seccomp=builtin', args)
            self.assertIn('--security-opt=no-new-privileges=true', args)

    def test_fixed_profile_snapshot_and_full_request_binding(self):
        original = sample_wrapper()
        plan = deepcopy(original['trace_report']['plan'])
        raw = encode_observed_trace_request(plan)
        value = json.loads(raw)
        self.assertEqual(set(value), {'worker_version', 'trace', 'observation_profile'})
        self.assertEqual(value['observation_profile'], views.PROFILE)
        plan['skip_indices'] = []
        self.assertEqual(value['trace'], original['trace_report']['plan'])
        with patch('entrotter_engine.consumer_observations._run_trace_observed', return_value=original) as run:
            result = execute_request(raw, _worker_alarm=True)
        self.assertEqual(result, {'worker_version': '1', 'request_id': sha256(raw).hexdigest(), 'report': original})
        run.assert_called_once_with(value['trace'], _worker_alarm=True)

    def test_closed_envelope_rejects_injected_code_profile_plan_and_oversize(self):
        good = json.loads(encode_observed_trace_request(sample_wrapper()['trace_report']['plan']))
        invalid = [{**good, 'observation_profile': 'custom'}, {**good, 'worker_version': '2'},
                   {**good, 'callback': 'unsafe'}, {**good, '_worker_alarm': True},
                   {**good, 'trace': {}}, {**good, 'scenario': {}}]
        with patch('entrotter_engine.consumer_observations._run_trace_observed') as run:
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    execute_request(canonical(value), _worker_alarm=True)
            with self.assertRaises(ValueError):
                execute_request(canonical(good) + b' ' * 262144, _worker_alarm=True)
        run.assert_not_called()

    def test_default_cli_without_worker_never_calls_native_or_overwrites_export(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / 'plan.json'
            plan.write_bytes(canonical(sample_wrapper()['trace_report']['plan']))
            output = Path(directory) / 'output.json'
            output.write_text('incumbent')
            with patch.dict(os.environ, {'ENTROTTER_WORKER_IMAGE': ''}), patch(
                'entrotter_engine.consumer_observations.run_trace_observed_native'
            ) as native, redirect_stderr(StringIO()), redirect_stdout(StringIO()) as stdout:
                self.assertEqual(main(['trace-observe', str(plan), '-o', str(output)]), 1)
                self.assertEqual(stdout.getvalue(), '')
            native.assert_not_called()
            self.assertEqual(output.read_text(), 'incumbent')

    def test_worker_guard_caps_and_restores_original_remaining_time(self):
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM)}
        for alarm, expected in [(180., 150.), (40., 40.)]:
            with patch.object(signal, 'getitimer', return_value=(alarm, 0.)), patch.object(
                signal, 'setitimer'
            ) as timer, patch.object(signal, 'signal') as handler, patch.object(
                views.time, 'monotonic', side_effect=[100., 100., 103.]
            ):
                with views._deadline_guard(_worker_alarm=True):
                    pass
            self.assertEqual(timer.call_args_list[0].args, (signal.ITIMER_REAL, expected))
            self.assertEqual(timer.call_args_list[-1].args, (signal.ITIMER_REAL, alarm - 3.))
            self.assertEqual([call.args for call in handler.call_args_list[-2:]], list(handlers.items()))

    def test_worker_guard_rejects_missing_or_periodic_alarm_and_expired_outer_deadline(self):
        for alarm in [(0., 0.), (30., 2.)]:
            with patch.object(signal, 'getitimer', return_value=alarm), self.assertRaises(ExecutionError):
                with views._deadline_guard(_worker_alarm=True):
                    self.fail('unsafe timer entered')
        with patch.object(signal, 'getitimer', return_value=(1., 0.)), patch.object(
            signal, 'setitimer'
        ), patch.object(signal, 'signal'), patch.object(views.time, 'monotonic', side_effect=[100., 100., 102.]):
            with self.assertRaises(views.ObservationStopped) as caught:
                with views._deadline_guard(_worker_alarm=True):
                    pass
        self.assertEqual(caught.exception.code, 'deadline')

    def test_clock_sampling_delay_cannot_extend_inherited_deadline(self):
        with patch.object(signal, 'getitimer', return_value=(1., 0.)), patch.object(
            signal, 'setitimer'
        ) as timer, patch.object(signal, 'signal'), patch.object(
            views.time, 'monotonic', side_effect=[100., 100.5, 100.5]
        ):
            with views._deadline_guard(_worker_alarm=True):
                pass
        self.assertEqual(timer.call_args_list[0].args, (signal.ITIMER_REAL, .5))
        self.assertEqual(timer.call_args_list[-1].args, (signal.ITIMER_REAL, .5))

    def test_worker_sigterm_unwinds_owned_context_and_restores_outer_alarm(self):
        previous = signal.getsignal(signal.SIGALRM)
        signal.setitimer(signal.ITIMER_REAL, 20.)
        cleanup = []
        try:
            with self.assertRaises(views.ObservationStopped) as caught:
                with views._deadline_guard(_worker_alarm=True):
                    try:
                        os.kill(os.getpid(), signal.SIGTERM)
                    finally:
                        cleanup.append('owned cleanup')
            self.assertEqual(caught.exception.code, 'cancelled')
            self.assertEqual(cleanup, ['owned cleanup'])
            self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0.)
            self.assertLessEqual(signal.getitimer(signal.ITIMER_REAL)[0], 20.)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.)


class ObservedHostBindingTests(unittest.TestCase):
    setUp = harness.IsolatedProtocolTests.setUp
    assert_cleanup = harness.IsolatedProtocolTests.assert_cleanup

    @contextmanager
    def response(self, envelope):
        # Preserve the full32 fixture without exceeding Linux's per-string
        # environment limit. Only the fake client reads this owned test file.
        path = self.root / 'response.json'
        path.write_text(json.dumps(envelope))
        with patch.dict(os.environ, {'FAKE_RESPONSE': '', 'FAKE_RESPONSE_FILE': str(path)}):
            yield

    def invoke(self, report):
        plan = sample_wrapper()['trace_report']['plan']
        raw = encode_observed_trace_request(plan)
        envelope = {'worker_version': '1', 'request_id': sha256(raw).hexdigest(), 'report': report}
        with self.response(envelope):
            return views.run_trace_observed(plan)

    def test_valid_wrapper_and_resealed_foreign_plan_and_wrong_family(self):
        original = sample_wrapper()
        self.assertEqual(self.invoke(original), original)
        self.assert_cleanup()
        foreign = deepcopy(original)
        foreign['trace_report']['plan']['skip_indices'] = []
        foreign['trace_report'] = seal(foreign['trace_report'])
        foreign['trace_artifact_id'] = foreign['trace_report']['artifact_id']
        foreign = seal(foreign)
        # This remains internally valid, but belongs to a different request.
        self.assertTrue(views.verify_observed_trace(foreign))
        for value in [foreign, original['trace_report'], {**original, 'artifact_id': '0' * 64}]:
            with self.subTest(value=str(value)[:40]), self.assertRaises(ExecutionError):
                self.invoke(value)
            self.assert_cleanup()

    def test_profile_is_in_request_hash_and_plain_trace_job_refuses_wrapper(self):
        from entrotter_engine.trace import run_trace
        from entrotter_engine.worker_protocol import encode_trace_request

        observed = sample_wrapper()
        plan = observed['trace_report']['plan']
        trace_hash = sha256(encode_trace_request(plan)).hexdigest()
        response = {'worker_version': '1', 'request_id': trace_hash, 'report': observed}
        with self.response(response):
            with self.assertRaisesRegex(ExecutionError, 'request binding'):
                views.run_trace_observed(plan)
            self.assert_cleanup()
            with self.assertRaisesRegex(ExecutionError, 'integrity or plan binding'):
                run_trace(plan)
            self.assert_cleanup()

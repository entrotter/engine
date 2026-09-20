"""JSON agent transport regressions; mocks are not kernel-isolation evidence."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from entrotter_engine.agent import AgentController, AgentError, RiskPolicy
from entrotter_engine.artifact import canonical
from entrotter_engine.runner import run_agent, run_agent_native
from entrotter_engine.worker_protocol import encode_agent_request, execute_request


def scenario():
    return json.loads((Path(__file__).parent / 'data/local.json').read_text())


def configuration():
    return {'decision_steps': [0, 1], 'max_requested_gas': 2000000, 'recording': None}


class AgentWorkerProtocolTests(unittest.TestCase):
    def test_default_agent_entrypoint_cannot_fall_back_to_native(self):
        with patch('entrotter_engine.isolated.client', side_effect=RuntimeError('no daemon')), \
             patch('entrotter_engine.runner.run_agent_native') as native:
            with self.assertRaisesRegex(RuntimeError, 'no daemon'):
                run_agent(scenario(), decision_steps=[0, 1])
            native.assert_not_called()

    def test_arbitrary_provider_object_is_not_a_public_argument(self):
        with patch('entrotter_engine.runner.run_agent_native') as native:
            with self.assertRaises(TypeError):
                run_agent(scenario(), AgentController(RiskPolicy(), [0]))
            native.assert_not_called()

    def test_invalid_decision_configuration_fails_before_docker(self):
        bad = [{**configuration(), 'decision_steps': steps} for steps in
               [[], [0, 0], [32], [True], [2], '0', None]]
        bad += [{**configuration(), 'max_requested_gas': x} for x in [True, 0, 64000001]]
        bad += [{**configuration(), 'recording': x} for x in [{}, [], 'import:evil']]
        bad += [{**configuration(), 'command': 'evil'}, {'decision_steps': [0]}]
        with patch('entrotter_engine.isolated.client') as client:
            for config in bad:
                with self.subTest(config=config), self.assertRaises((ValueError, AgentError)):
                    encode_agent_request(scenario(), config)
            client.assert_not_called()
        s = scenario()
        s['steps'][0]['candidate'] = None
        with self.assertRaises(ValueError):
            encode_agent_request(s, configuration())

    def test_fixture_cannot_select_an_agent(self):
        s = json.loads((Path(__file__).parent / 'data/fixture.json').read_text())
        with self.assertRaisesRegex(ValueError, 'EVM'):
            encode_agent_request(s, configuration())

    def test_worker_validates_unknown_or_oversized_requests_before_execution(self):
        request = json.loads(encode_agent_request(scenario(), configuration()))
        cases = [b'[]', b'null', b'{}', b' ', b'x' * (4 * 1024 * 1024 + 1)]
        cases += [canonical({**request, 'command': 'evil'}),
                  canonical({**request, 'worker_version': '2'}),
                  canonical({**request, 'agent': {**configuration(), 'import': 'evil'}})]
        with patch('entrotter_engine.runner.run_agent_native') as agent, \
             patch('entrotter_engine.runner.run_native') as native:
            for raw in cases:
                with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                    execute_request(raw)
            agent.assert_not_called()
            native.assert_not_called()

    def test_normal_worker_still_limits_input_to_256_kib(self):
        s = json.loads((Path(__file__).parent / 'data/fixture.json').read_text())
        raw = canonical(s) + b' ' * 262144
        with patch('entrotter_engine.runner.run_native') as native:
            with self.assertRaisesRegex(ValueError, '256 KiB'):
                execute_request(raw)
            native.assert_not_called()

    def test_envelope_binds_result_to_entire_request(self):
        from hashlib import sha256
        raw = encode_agent_request(scenario(), configuration())
        with patch('entrotter_engine.runner.run_agent_native', return_value={'sentinel': 1}) as native:
            response = execute_request(raw)
        self.assertEqual(response, {'worker_version': '1', 'request_id': sha256(raw).hexdigest(),
                                    'report': {'sentinel': 1}})
        self.assertEqual(native.call_args.args[0], scenario())
        self.assertEqual(native.call_args.args[1].steps, {0, 1})
        self.assertEqual(native.call_args.args[1].remaining_gas, 2000000)

    def test_native_provider_keeps_single_use_and_prelaunch_validation(self):
        controller = AgentController(RiskPolicy(), [0])
        with patch('entrotter_engine.runner.run_evm', return_value={}) as evm:
            run_agent_native(scenario(), controller)
            with self.assertRaisesRegex(AgentError, 'single-use'):
                run_agent_native(scenario(), controller)
            self.assertEqual(evm.call_count, 1)
        s = deepcopy(scenario())
        s['steps'][0]['candidate'] = None
        with patch('entrotter_engine.runner.run_evm') as evm:
            with self.assertRaises(ValueError):
                run_agent_native(s, AgentController(RiskPolicy(), [0]))
            evm.assert_not_called()


class AgentHostProtocolTests(unittest.TestCase):
    # Reuse only the fake-client harness, not its collected test methods.
    import test_isolated as harness
    setUp = harness.IsolatedProtocolTests.setUp
    assert_cleanup = harness.IsolatedProtocolTests.assert_cleanup

    def envelope(self):
        from hashlib import sha256
        report = json.loads((Path(__file__).parent / 'data/agent-recorded-local.json').read_text())
        raw = encode_agent_request(report['scenario'], {**configuration(), 'recording': report['agent']})
        return {'worker_version': '1', 'request_id': sha256(raw).hexdigest(), 'report': report}

    def invoke(self, response):
        import os
        report = self.envelope()['report']
        with patch.dict(os.environ, {'FAKE_RESPONSE': json.dumps(response)}):
            return run_agent(report['scenario'], decision_steps=[0, 1], recording=report['agent'])

    def test_bound_recording_is_accepted_and_owned_client_removed(self):
        envelope = self.envelope()
        self.assertEqual(self.invoke(envelope), envelope['report'])
        self.assert_cleanup()

    def test_old_wrong_or_extra_envelope_is_rejected(self):
        from entrotter_engine.evm import ExecutionError
        good = self.envelope()
        for response in [good['report'], [], {**good, 'extra': True},
                         {**good, 'worker_version': '2'}, {**good, 'request_id': '0' * 64}]:
            with self.subTest(response=str(response)[:60]), self.assertRaises(ExecutionError):
                self.invoke(response)
            self.assert_cleanup()

    def test_bad_recording_hash_and_scenario_are_rejected(self):
        from entrotter_engine.artifact import seal
        from entrotter_engine.evm import ExecutionError
        good = self.envelope()
        changed = deepcopy(good['report'])
        changed['scenario']['title'] = 'wrong scenario'
        bad_record = deepcopy(good['report'])
        bad_record['agent']['exchanges'][0]['response']['choice'] = 'shell'
        for report in [None, [], {}, {**good['report'], 'artifact_id': '0' * 64},
                       seal(changed), seal(bad_record)]:
            with self.subTest(report=str(report)[:60]), self.assertRaises(ExecutionError):
                self.invoke({**good, 'report': report})
            self.assert_cleanup()

    def test_oversized_recording_fails_before_launch(self):
        from entrotter_engine.agent import AgentError, MAX_RECORDING_BYTES
        report = self.envelope()['report']
        report['agent']['provider']['oversized'] = 'x' * MAX_RECORDING_BYTES
        with patch('entrotter_engine.isolated.client') as client:
            with self.assertRaises(AgentError):
                run_agent(report['scenario'], decision_steps=[0, 1], recording=report['agent'])
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()

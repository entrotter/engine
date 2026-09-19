"""Actual Docker + Anvil risk decisions and frozen model replay; never calls a model."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from entrotter_engine.agent import AgentController, RiskPolicy
from entrotter_engine.artifact import seal, verify
from entrotter_engine.evm import ExecutionError
from entrotter_engine.isolated import _slot, client
from entrotter_engine.runner import run_agent, run_agent_native

ROOT = Path(__file__).resolve().parents[1]


def recorded():
    return json.loads((ROOT / 'tests/data/agent-recorded-local.json').read_text())


class BoundedAgentTests(unittest.TestCase):
    def assert_worker_removed(self):
        with client() as prefix:
            self.assertIsNone(_slot(prefix))

    def test_risk_matches_native_and_replays_complete_artifact(self):
        scenario = recorded()['scenario']
        expected = run_agent_native(scenario, AgentController(RiskPolicy(), [0, 1]))
        actual = run_agent(scenario, decision_steps=[0, 1])
        self.assertEqual(actual, expected)
        self.assertEqual([x['response']['choice'] for x in actual['agent']['exchanges']], ['execute', 'hold'])
        replayed = run_agent(scenario, decision_steps=[0, 1], recording=actual['agent'])
        self.assertEqual(replayed, expected)
        self.assert_worker_removed()

    def test_frozen_model_recording_replays_without_provider_or_network(self):
        expected = recorded()
        self.assertTrue(verify(expected))
        self.assertEqual(expected['artifact_id'], '1d1de88d01cbe23c494f6a6f7ee7127d63629baac071def58c067506ddf5893b')
        actual = run_agent(expected['scenario'], decision_steps=[0, 1], recording=expected['agent'])
        self.assertEqual(actual, expected)
        self.assert_worker_removed()

    def test_recording_larger_than_scenario_budget_stays_valid(self):
        expected = recorded()
        expected['agent']['provider']['transport_test_padding'] = 'x' * 262144
        expected = seal(expected)
        actual = run_agent(expected['scenario'], decision_steps=[0, 1], recording=expected['agent'])
        self.assertEqual(actual, expected)
        self.assert_worker_removed()

    def test_diverged_recording_and_gas_budget_fail_then_next_run_succeeds(self):
        expected = recorded()
        changed = deepcopy(expected['scenario'])
        changed['actor_balance_wei'] = '10000000000000000001'
        for scenario, budget in [(changed, 2000000), (expected['scenario'], 21000)]:
            with self.subTest(budget=budget), self.assertRaises(ExecutionError):
                run_agent(scenario, decision_steps=[0, 1], recording=expected['agent'], max_requested_gas=budget)
            self.assert_worker_removed()
        self.assertEqual(run_agent(expected['scenario'], decision_steps=[0, 1], recording=expected['agent']), expected)

    def test_risk_respects_tight_requested_gas_budget(self):
        s = recorded()['scenario']
        # Both proposals are successful transfers, but only the first fits.
        s['steps'][1]['candidate'] = deepcopy(s['steps'][0]['candidate'])
        result = run_agent(s, decision_steps=[0, 1], max_requested_gas=21000)
        self.assertEqual([x['response']['choice'] for x in result['agent']['exchanges']], ['execute', 'hold'])
        self.assertEqual(result['agent']['exchanges'][1]['request']['limits']['remaining_requested_gas'], 0)
        self.assert_worker_removed()


if __name__ == '__main__':
    unittest.main()

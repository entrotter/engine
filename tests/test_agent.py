"""Causal boundary unit checks and separately labelled actual Anvil executions."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from entrotter_engine.agent import (AgentController, AgentError, ReplayPolicy,
                                    RiskPolicy, observe, validate_decision)
from entrotter_engine.artifact import verify
from entrotter_engine.evm import AnvilSession
from entrotter_engine.rpc import RPCError, RPCRejected
from entrotter_engine.runner import run_native as run, run_agent_native as run_agent


def scenario():
    return json.loads((Path(__file__).parent / "data/local.json").read_text())


class CurrentNode:
    """Unit-only current state stub; not historical or Anvil evidence."""
    def call(self, method, params):
        return {"eth_getBlockByNumber": {"number": "0x2", "hash": "0x" + "a" * 64, "timestamp": "0x1"},
                "eth_chainId": "0x7a69",
                "eth_getBalance": "0x10", "eth_call": "0x"}[method]


def observation(rpc=None):
    s = scenario()
    return observe(rpc or CurrentNode(), step=0, actor=s["actor"],
                   action=s["steps"][0]["candidate"], tokens=[], balances={},
                   previous=[], gas_remaining=21000)


class AgentBoundaryTests(unittest.TestCase):
    def test_strict_responses_and_observation_binding(self):
        request = observation()
        good = RiskPolicy().decide(request)
        bad = [None, [], {}, {**good, "choice": "shell"}, {**good, "choice": []},
               {**good, "request_id": "0" * 64}, {**good, "to": scenario()["actor"]},
               {**good, "reason": ""}, {**good, "reason": "x" * 1001},
               {**good, "reason": float("nan")}]
        for response in bad:
            with self.subTest(response=str(response)[:60]), self.assertRaises(AgentError):
                validate_decision(request, response)
        self.assertEqual(validate_decision(request, good), good)

    def test_preflight_transport_failure_is_not_a_policy_rejection(self):
        with patch.object(CurrentNode, "call", side_effect=RPCError("injected transport")):
            with self.assertRaises(RPCError):
                observation()

    def test_rejected_preflight_records_no_provider_error_text(self):
        original = CurrentNode.call
        def reject(rpc, method, params):
            if method == "eth_call":
                raise RPCRejected("private upstream detail")
            return original(rpc, method, params)
        with patch.object(CurrentNode, "call", reject):
            request = observation()
        self.assertEqual(request["preflight"], {"status": "rejected", "return_data": None})
        self.assertNotIn("private", json.dumps(request))
        self.assertEqual(RiskPolicy().decide(request)["choice"], "hold")

    def test_malformed_preflight_is_not_success(self):
        original = CurrentNode.call
        for raw in [None, "0xabc", "secret", "0x" + "00" * 4097]:
            def result(rpc, method, params):
                return raw if method == "eth_call" else original(rpc, method, params)
            with self.subTest(raw=str(raw)[:20]), patch.object(CurrentNode, "call", result):
                with self.assertRaises(AgentError):
                    observation()

    def test_provider_mutation_cannot_replace_transaction(self):
        class MutatingPolicy(RiskPolicy):
            def decide(self, request):
                response = super().decide(request)
                request["proposed_action"]["to"] = "0x" + "f" * 40
                return response
        controller = AgentController(MutatingPolicy(), [0])
        s = scenario()
        action = s["steps"][0]["candidate"]
        chosen, _ = controller.choose(CurrentNode(), step=0, actor=s["actor"], action=action,
                                       tokens=[], balances={}, previous=[])
        self.assertEqual(chosen, action)
        self.assertEqual(controller.recording()["exchanges"][0]["request"]["proposed_action"], action)

    def test_gas_budget_enforced_even_when_policy_ignores_it(self):
        class Execute(RiskPolicy):
            def decide(self, request):
                return {"request_id": request["request_id"], "choice": "execute", "reason": "test"}
        controller = AgentController(Execute(), [1], max_requested_gas=21000)
        s = scenario()
        with self.assertRaisesRegex(AgentError, "gas budget"):
            controller.choose(CurrentNode(), step=1, actor=s["actor"], action=s["steps"][1]["candidate"],
                              tokens=[], balances={}, previous=[])

    def test_invalid_selection_fails_before_launch(self):
        for steps in [[31], [0]]:
            s = scenario()
            s["steps"][0]["candidate"] = None
            with patch("entrotter_engine.evm.AnvilSession") as launch:
                with self.assertRaises(ValueError):
                    run_agent(s, AgentController(RiskPolicy(), steps))
                launch.assert_not_called()

    def test_replay_checks_content_not_only_supplied_digest(self):
        request = observation()
        recording = {"agent_version": "0.1.0", "provider": RiskPolicy.metadata,
                     "exchanges": [{"request": request, "response": RiskPolicy().decide(request)}]}
        changed = deepcopy(request)
        changed["observation"]["native_balance_wei"] = "17"
        with self.assertRaisesRegex(AgentError, "diverged"):
            ReplayPolicy(recording).decide(changed)
        recording["exchanges"][0]["request"] = changed
        with self.assertRaises(AgentError):
            ReplayPolicy(recording)

    def test_recording_bounds_exhaustion_and_unused_entries(self):
        request = observation()
        recording = {"agent_version": "0.1.0", "provider": RiskPolicy.metadata,
                     "exchanges": [{"request": request, "response": RiskPolicy().decide(request)}]}
        for raw in [None, [], {}, {**recording, "provider": None},
                    {**recording, "exchanges": []}, {**recording, "exchanges": [{}]},
                    {**recording, "extra": True}]:
            with self.subTest(raw=raw), self.assertRaises(AgentError):
                ReplayPolicy(raw)
        replay = ReplayPolicy(recording)
        with self.assertRaisesRegex(AgentError, "Unused"):
            replay.finish()
        replay.decide(request)
        replay.finish()
        with self.assertRaisesRegex(AgentError, "exhausted"):
            replay.decide(request)


@unittest.skipUnless(shutil.which("anvil"), "Real Anvil executable required")
class ActualAgentAnvilTests(unittest.TestCase):
    def test_frozen_model_report_replays_exactly_without_calling_provider(self):
        expected = json.loads((Path(__file__).parent / 'data/agent-recorded-local.json').read_text())
        self.assertTrue(verify(expected))
        self.assertEqual(expected['artifact_id'], '1d1de88d01cbe23c494f6a6f7ee7127d63629baac071def58c067506ddf5893b')
        actual = run_agent(expected['scenario'], AgentController(ReplayPolicy(expected['agent']), [0, 1]))
        self.assertEqual(actual, expected)

    def test_risk_avoids_revert_and_replays_exact_complete_artifact(self):
        s = scenario()
        s["steps"] = [{"baseline": deepcopy(x["candidate"]), "candidate": x["candidate"]} for x in s["steps"]]
        prescribed = run(s)
        controller = AgentController(RiskPolicy(), [0, 1])
        report = run_agent(s, controller)
        self.assertTrue(verify(report))
        self.assertEqual(report["baseline"], prescribed["baseline"])
        self.assertEqual([x["status"] for x in report["candidate"]["trace"]], ["success", "noop"])
        self.assertEqual([x["response"]["choice"] for x in report["agent"]["exchanges"]], ["execute", "hold"])
        self.assertEqual(report["candidate"]["metrics"]["reverted_transactions"], 0)
        self.assertLess(int(report["candidate"]["metrics"]["gas_used"]), int(prescribed["candidate"]["metrics"]["gas_used"]))
        replay = run_agent(s, AgentController(ReplayPolicy(report["agent"]), [0, 1]))
        self.assertEqual(report, replay)
        with self.assertRaisesRegex(AgentError, "single-use"):
            run_agent(s, controller)

    def test_future_changes_and_scenario_labels_do_not_reach_policy(self):
        first = scenario()
        second = deepcopy(first)
        second["title"] = "Secret future scenario label"
        second["steps"][1]["candidate"] = None
        a = run_agent(first, AgentController(RiskPolicy(), [0]))
        b = run_agent(second, AgentController(RiskPolicy(), [0]))
        self.assertEqual(a["agent"], b["agent"])
        self.assertNotIn("Secret", json.dumps(b["agent"]))
        self.assertNotIn("agent", run(first))

    def test_agent_fault_or_cancellation_reaps_nodes(self):
        for failure in [AgentError("injected provider fault"), KeyboardInterrupt()]:
            sessions = []
            class TrackedSession(AnvilSession):
                def __enter__(self):
                    sessions.append(self)
                    return super().__enter__()
            class BrokenPolicy(RiskPolicy):
                def decide(self, request):
                    raise failure
            with patch("entrotter_engine.evm.AnvilSession", TrackedSession):
                with self.assertRaises(type(failure)):
                    run_agent(scenario(), AgentController(BrokenPolicy(), [0]))
            self.assertEqual(len(sessions), 2)
            for session in sessions:
                self.assertIsNotNone(session.process.poll())
                with socket.socket() as sock:
                    sock.settimeout(.2)
                    self.assertNotEqual(sock.connect_ex(("127.0.0.1", urlsplit(session.rpc.url).port)), 0)


if __name__ == "__main__":
    unittest.main()

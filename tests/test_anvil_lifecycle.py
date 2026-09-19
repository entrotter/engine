"""Real subprocess/receipt checks; fault injection is labelled, never a fake EVM."""
import json
from pathlib import Path
import shutil
import socket
import unittest
from unittest.mock import patch

from entrotter_engine.evm import AnvilSession, ExecutionError
from entrotter_engine.rpc import RPC, RPCError
from entrotter_engine.runner import run


@unittest.skipUnless(shutil.which("anvil"), "Real Anvil executable required")
class AnvilLifecycleTests(unittest.TestCase):
    def scenario(self):
        return json.loads((Path(__file__).parent / "data/local.json").read_text())

    def assert_closed(self, session):
        self.assertIsNotNone(session.process.poll(), "Owned Anvil process leaked")
        from urllib.parse import urlsplit
        port = urlsplit(session.rpc.url).port
        with socket.socket() as sock:
            sock.settimeout(.2)
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)

    def test_simultaneous_nodes_have_isolated_mutable_state(self):
        actor = self.scenario()["actor"]
        with AnvilSession() as first, AnvilSession() as second:
            self.assertNotEqual(first.rpc.url, second.rpc.url)
            original = second.rpc.call("eth_getBalance", [actor, "latest"])
            first.rpc.call("anvil_setBalance", [actor, "0x123"])
            self.assertEqual(first.rpc.call("eth_getBalance", [actor, "latest"]), "0x123")
            self.assertEqual(second.rpc.call("eth_getBalance", [actor, "latest"]), original)
        self.assert_closed(first)
        self.assert_closed(second)

    def test_rejected_transaction_is_not_a_revert_or_success(self):
        scenario = self.scenario()
        scenario["steps"] = [{"baseline": None, "candidate": {
            "to": scenario["allowed_targets"][0],
            "value_wei": "100000000000000000000", "gas": 21000}}]
        report = run(scenario)
        self.assertEqual(report["candidate"]["trace"][0]["status"], "rejected")
        metrics = report["candidate"]["metrics"]
        self.assertEqual(metrics["rejected_transactions"], 1)
        self.assertEqual(metrics["reverted_transactions"], 0)
        self.assertEqual(metrics["gas_used"], "0")
        self.assertEqual(metrics["balance_delta_wei"], "0")
        self.assertEqual(report["baseline"]["start_timestamp"], report["candidate"]["start_timestamp"])

    def test_keyboard_cancellation_reaps_process_and_closes_port(self):
        session = AnvilSession()
        with self.assertRaises(KeyboardInterrupt):
            with session:
                raise KeyboardInterrupt("Injected caller cancellation")
        self.assert_closed(session)

    def test_rpc_fault_reaps_process_and_closes_port(self):
        session = AnvilSession()
        with self.assertRaises(RPCError):
            with session:
                raise RPCError("Injected transport failure after real startup")
        self.assert_closed(session)

    def test_startup_timeout_reaps_real_subprocess(self):
        session = AnvilSession()
        # Advance the startup deadline, while still launching a real Anvil child.
        with patch("entrotter_engine.evm.time.monotonic", side_effect=[0, 26]):
            with self.assertRaisesRegex(ExecutionError, "startup timed out"):
                session.__enter__()
        self.assert_closed(session)

    def test_startup_cancellation_reaps_real_subprocess(self):
        session = AnvilSession()
        with patch.object(RPC, "call", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                session.__enter__()
        self.assert_closed(session)

    def test_missing_receipt_fails_whole_run_and_cleans_up(self):
        sessions = []
        original_call = RPC.call

        class TrackedSession(AnvilSession):
            def __enter__(self):
                sessions.append(self)
                return super().__enter__()

        def fail_receipt(rpc, method, params=None):
            if method == "eth_getTransactionReceipt":
                return None
            return original_call(rpc, method, params)

        with patch("entrotter_engine.evm.AnvilSession", TrackedSession):
            with patch.object(RPC, "call", fail_receipt):
                with self.assertRaisesRegex(ExecutionError, "No receipt"):
                    run(self.scenario())
        self.assertEqual(len(sessions), 2)
        for session in sessions:
            self.assert_closed(session)

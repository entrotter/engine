"""Supported fixed views, finite errors, cancellation and content/export binding."""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from entrotter_engine import consumer_observations as views
from entrotter_engine.__main__ import main
from entrotter_engine.artifact import seal
from entrotter_engine.evm import ExecutionError
from entrotter_engine.rpc import RPC, RPCError
from entrotter_engine.trace import _run_trace_native

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "0x3333333333333333333333333333333333333333"
AGGREGATOR = "0x4444444444444444444444444444444444444444"


def word(number):
    return "0x" + number.to_bytes(32, "big").hex()


def address(value):
    return "0x" + "0" * 24 + value[2:]


def round_data(price):
    return "0x" + "".join(word(value)[2:] for value in (price, price, 1, 2, price))


class FakeRPC:
    def __init__(self, head, price=10, fault=None):
        self.timeout = 10
        self.head, self.price, self.fault = {"timestamp": "0x1", **head}, price, fault
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, deepcopy(params), self.timeout))
        if self.fault:
            result = self.fault(method, params)
            if result is not None:
                return result
        if method == "eth_getBlockByNumber":
            return self.head
        if method == "eth_getCode":
            return "0x60006000f3"
        selector = params[0]["data"][:10]
        return {
            views.SELECTORS["source"]: address(SOURCE),
            views.SELECTORS["price"]: word(self.price),
            views.SELECTORS["base_currency"]: address(views.ZERO),
            views.SELECTORS["base_unit"]: word(views.UNIT),
            views.SELECTORS["aggregator"]: address(AGGREGATOR),
            views.SELECTORS["latest_round_data"]: round_data(self.price),
        }[selector]


def sample_wrapper():
    report = json.loads(
        (ROOT / "evidence/aave-consumer-price/native-006/report.json").read_text()
    )
    collector = views.OwnedPriceObserver()
    for index, (branch, phase) in enumerate(views.PHASES):
        head = {
            "number": hex(report["source"]["parent"]["block_number"] + index % 2),
            "timestamp": hex(report["source"]["header"]["timestamp"] - (1 - index % 2)),
            "hash": report["source"]["parent"]["block_hash"]
            if index % 2 == 0
            else "0x" + "ab" * 32,
        }
        collector.observe(
            FakeRPC(head, 20 if index == 1 else 10),
            branch,
            phase,
            time.monotonic() + 10,
        )
    return seal(
        {
            "observation_version": views.OBSERVATION_VERSION,
            "profile": views.PROFILE,
            "trace_report": report,
            "trace_artifact_id": report["artifact_id"],
            "observations": collector.rows,
            "classification": views._classification(collector.rows, report),
            "scope": views.SCOPE,
        }
    )


class ConsumerObservationTests(unittest.TestCase):
    def test_fixed_dynamic_source_and_nine_reads_with_timeout_restore(self):
        rpc = FakeRPC({"number": "0x1", "hash": "0x" + "11" * 32})
        collector = views.OwnedPriceObserver()
        collector.observe(rpc, "baseline", "before", time.monotonic() + 3)
        self.assertEqual(len(rpc.calls), 9)
        self.assertTrue(all(0 < c[2] <= 2 for c in rpc.calls))
        self.assertEqual(rpc.timeout, 10)
        self.assertEqual(rpc.calls[6][:2], ("eth_getCode", [SOURCE, "latest"]))
        self.assertEqual(rpc.calls[7][1][0]["to"], SOURCE)
        self.assertEqual(collector.rows[0]["raw"]["source"], address(SOURCE))

    def test_invalid_phase_and_deadline_refuse_before_rpc(self):
        rpc = FakeRPC({})
        collector = views.OwnedPriceObserver()
        for branch, phase, deadline in [
            ("candidate", "after", 1),
            ("baseline", "before", float("nan")),
            ("baseline", "before", float("inf")),
            ("baseline", "before", True),
        ]:
            with self.assertRaises(ValueError):
                collector.observe(rpc, branch, phase, deadline)
        self.assertEqual(rpc.calls, [])
        with self.assertRaises(views.ObservationStopped):
            collector.observe(rpc, "baseline", "before", time.monotonic() - 1)
        self.assertEqual(rpc.calls, [])

    def test_four_unique_phases_duplicate_and_fifth_never_read(self):
        collector = views.OwnedPriceObserver()
        rpc = FakeRPC({"number": "0x1", "hash": "0x" + "11" * 32})
        for branch, phase in views.PHASES:
            collector.observe(rpc, branch, phase, time.monotonic() + 10)
        self.assertEqual(len(rpc.calls), 36)
        with self.assertRaises(ValueError):
            collector.observe(rpc, "baseline", "before", time.monotonic() + 10)
        self.assertEqual(len(rpc.calls), 36)

    def test_late_success_does_not_continue_past_shared_deadline(self):
        collector = views.OwnedPriceObserver()
        rpc = FakeRPC({"number": "0x1", "hash": "0x" + "11" * 32})
        with (
            patch(
                "entrotter_engine.consumer_observations.time.monotonic",
                side_effect=[1, 11],
            ),
            self.assertRaises(views.ObservationStopped),
        ):
            collector.observe(rpc, "baseline", "before", 10)
        self.assertEqual(len(rpc.calls), 1)
        self.assertEqual(collector.rows, [])
        self.assertEqual(rpc.timeout, 10)

    def test_hostile_error_finite_and_no_source_no_dependent_calls(self):
        def fault(method, params):
            if (
                method == "eth_call"
                and params[0]["data"][:10] == views.SELECTORS["source"]
            ):
                raise RPCError(
                    "SECRET https://private.invalid/token",
                    code="timeout",
                    method="eth_call",
                )

        rpc = FakeRPC({"number": "0x1", "hash": "0x" + "11" * 32}, fault=fault)
        collector = views.OwnedPriceObserver()
        collector.observe(rpc, "baseline", "before", time.monotonic() + 10)
        self.assertEqual(len(rpc.calls), 6)
        self.assertNotIn("SECRET", json.dumps(collector.rows))
        self.assertEqual(
            collector.rows[0]["errors"][0]["diagnostics"],
            {"code": "timeout", "method": "eth_call"},
        )
        self.assertEqual(len(collector.rows[0]["errors"]), 4)

    def test_stop_through_actual_rpc_mapping_restores_timeout(self):
        rpc = RPC("http://127.0.0.1:1", local=True)
        for error in (
            views.ObservationStopped("cancelled"),
            KeyboardInterrupt(),
            SystemExit(7),
        ):
            with (
                self.subTest(kind=type(error).__name__),
                patch.object(rpc.opener, "open", side_effect=error),
            ):
                collector = views.OwnedPriceObserver()
                with self.assertRaises(type(error)):
                    collector.observe(rpc, "baseline", "before", time.monotonic() + 10)
                self.assertEqual(collector.rows, [])
                self.assertEqual(rpc.timeout, 10)

    def test_strict_abi_and_code_bounds(self):
        for raw in ("0x", "0x01", word(1) + "00", "0x" + "ff" * 12 + "00" * 20):
            with self.assertRaises(ValueError):
                views._address(raw)
        self.assertEqual(views._code("0x" + "00" * 65536)["bytes"], 65536)
        with self.assertRaises(ValueError):
            views._code("0x" + "00" * 65537)
        with self.assertRaises(ValueError):
            views._round("0x" + "00" * 159)
        with self.assertRaises(ValueError):
            views._round("0x" + "".join(word(x)[2:] for x in (2**80, 1, 1, 2, 1)))

    def test_wrapper_receipt_preservation_classification_and_export(self):
        result = sample_wrapper()
        self.assertTrue(views.verify_observed_trace(result))
        self.assertTrue(result["classification"]["complete_price_views"])
        self.assertEqual(result["classification"]["price_difference"], -10)
        original = json.loads(
            (ROOT / "evidence/aave-consumer-price/native-006/report.json").read_text()
        )
        self.assertEqual(result["trace_report"], original)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, {"ENTROTTER_EXPORT_STATE_DIR": directory + "/state"}
            ),
        ):
            path = Path(directory) / "observed.json"
            views.write_observed_trace(result, path)
            self.assertEqual(views.load_observed_trace(path), result)
            path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                views.load_observed_trace(path)

    def test_fully_resealed_contradictions_refused(self):
        original = sample_wrapper()
        mutations = [
            lambda r: r.update(trace_artifact_id="0" * 64),
            lambda r: r["classification"].update(price_difference=100),
            lambda r: r["classification"].update(complete_price_views=1),
            lambda r: r["observations"][0]["head"].update(hash="0x" + "ff" * 32),
            lambda r: r["observations"][1]["head"].update(timestamp=1),
            lambda r: r["observations"][0].update(phase="after"),
            lambda r: r["observations"][0]["raw"].update(price="SECRET"),
            lambda r: r["observations"][0]["code"]["oracle_code"].update(bytes=True),
            lambda r: r["observations"][0]["errors"].append(
                {"query": "source", "category": "invalid_response"}
            ),
        ]
        for mutation in mutations:
            result = deepcopy(original)
            mutation(result)
            self.assertFalse(views.verify_observed_trace(seal(result)))

    def test_unsupported_source_unit_and_unverified_replay_stay_unproven(self):
        result = sample_wrapper()
        for change, reason in [
            (
                lambda r: r["observations"][1]["raw"].update(
                    source=address("0x5555555555555555555555555555555555555555")
                ),
                "source_changed",
            ),
            (
                lambda r: r["observations"][0]["raw"].update(base_unit=word(1)),
                "unsupported_currency_or_unit",
            ),
        ]:
            changed = deepcopy(result)
            change(changed)
            classification = views._classification(
                changed["observations"], changed["trace_report"]
            )
            self.assertFalse(classification["complete_price_views"])
            self.assertIn(reason, classification["unproven_reasons"])
            self.assertIsNone(classification["price_difference"])

    def test_read_completeness_separate_from_replay_verification(self):
        result = sample_wrapper()
        result["trace_report"]["baseline_verified"] = False
        result["trace_report"]["baseline"]["matches_original_receipts"] = False
        result["trace_report"] = seal(result["trace_report"])
        result["trace_artifact_id"] = result["trace_report"]["artifact_id"]
        result["classification"] = views._classification(
            result["observations"], result["trace_report"]
        )
        self.assertTrue(views.verify_observed_trace(seal(result)))
        self.assertTrue(result["classification"]["complete_price_views"])
        self.assertFalse(result["classification"]["baseline_receipts_verified"])

    def test_resealed_initial_timestamp_mismatch_cannot_claim_complete_views(self):
        result = sample_wrapper()
        result["observations"][2]["head"]["timestamp"] += 1
        self.assertFalse(views.verify_observed_trace(seal(result)))
        result["classification"] = views._classification(
            result["observations"], result["trace_report"]
        )
        self.assertFalse(result["classification"]["complete_price_views"])
        self.assertIn(
            "initial_heads_differ", result["classification"]["unproven_reasons"]
        )
        # Honest unproven records preserve the mismatched declaration.
        self.assertTrue(views.verify_observed_trace(seal(result)))

    def test_resealed_future_feed_metadata_is_explicitly_unproven(self):
        result = sample_wrapper()
        row = result["observations"][1]
        values = views._round(row["raw"]["latest_round_data"])
        future = row["head"]["timestamp"] + 1
        row["raw"]["latest_round_data"] = "0x" + "".join(
            word(value)[2:]
            for value in (
                values["round_id"],
                values["answer"],
                future,
                future,
                values["answered_in_round"],
            )
        )
        self.assertFalse(views.verify_observed_trace(seal(result)))
        result["classification"] = views._classification(
            result["observations"], result["trace_report"]
        )
        self.assertFalse(result["classification"]["complete_price_views"])
        self.assertIn(
            "feed_timestamp_unproven", result["classification"]["unproven_reasons"]
        )
        self.assertIsNone(result["classification"]["price_difference"])
        self.assertTrue(views.verify_observed_trace(seal(result)))

    def test_empty_code_and_malformed_supported_getters_are_unproven(self):
        result = sample_wrapper()
        result["observations"][0]["code"]["oracle_code"] = views._code("0x")
        classification = views._classification(
            result["observations"], result["trace_report"]
        )
        self.assertFalse(classification["complete_price_views"])
        self.assertIn("code_unavailable", classification["unproven_reasons"])
        rpc = FakeRPC(
            {"number": "0x1", "hash": "0x" + "11" * 32},
            fault=lambda m, p: "0x01" if m == "eth_call" else None,
        )
        collector = views.OwnedPriceObserver()
        collector.observe(rpc, "baseline", "before", time.monotonic() + 10)
        self.assertEqual(collector.rows[0]["raw"], {})
        self.assertEqual(len(collector.rows[0]["errors"]), 7)

    def test_fifo_loader_refuses_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fifo"
            os.mkfifo(path)
            with self.assertRaises(ValueError):
                views.load_observed_trace(path)

    def test_no_caller_callback_admission(self):
        with (
            self.assertRaises(ValueError),
            patch("entrotter_engine.trace.capture_source") as capture,
        ):
            _run_trace_native({}, object())
        capture.assert_not_called()

    def test_guard_restores_handlers_and_stops_signal(self):
        previous = {
            sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGALRM)
        }
        with self.assertRaises(views.ObservationStopped):
            with views._deadline_guard():
                os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        signal.setitimer(signal.ITIMER_REAL, 20)
        try:
            with self.assertRaises(ExecutionError):
                with views._deadline_guard():
                    self.fail("should not enter")
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def test_thread_context_refused_before_execution(self):
        results = []

        def run():
            try:
                views.run_trace_observed_native({})
            except ExecutionError:
                results.append("refused")

        with patch(
            "entrotter_engine.consumer_observations._run_trace_native"
        ) as execution:
            thread = threading.Thread(target=run)
            thread.start()
            thread.join(2)
            self.assertEqual(results, ["refused"])
            execution.assert_not_called()

    def test_cli_explicit_native_preserves_observation_export(self):
        with (
            patch(
                "entrotter_engine.consumer_observations.run_trace_observed_native",
                return_value=sample_wrapper(),
            ),
            patch(
                "entrotter_engine.consumer_observations.write_observed_trace"
            ) as writer,
            patch("entrotter_engine.trace.load_trace", return_value={}),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(
                main(["trace-observe", "unused", "--native", "-o", "result.json"]), 0
            )
            self.assertEqual(
                json.loads(stdout.getvalue())["complete_price_views"], True
            )
            writer.assert_called_once()

    def test_cli_stop_no_export(self):
        with (
            patch(
                "entrotter_engine.consumer_observations.run_trace_observed_native",
                side_effect=views.ObservationStopped("cancelled"),
            ),
            patch(
                "entrotter_engine.consumer_observations.write_observed_trace"
            ) as writer,
            patch("entrotter_engine.trace.load_trace", return_value={}),
            redirect_stderr(StringIO()) as stderr,
        ):
            self.assertEqual(
                main(["trace-observe", "unused", "--native", "-o", "result.json"]), 130
            )
            writer.assert_not_called()
            self.assertEqual(
                stderr.getvalue(), "Error: Owned consumer observation stopped\n"
            )

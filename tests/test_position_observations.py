"""Account views must be bound, complete and exact before reporting impact."""

from copy import deepcopy
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from entrotter_engine import position_observations as position
from entrotter_engine import consumer_observations as price
from entrotter_engine.artifact import seal
from entrotter_engine.rpc import RPCError
from test_consumer_observations import FakeRPC, sample_wrapper

ACCOUNT = "0x16aa9154557f1394089db90d3cbe212d9a7f33bb"


def words(values):
    return "0x" + "".join(v.to_bytes(32, "big").hex() for v in values)


def sample():
    observed = sample_wrapper()
    rows = []
    for i, (branch, phase) in enumerate(price.PHASES):
        rows.append(
            {
                "branch": branch,
                "phase": phase,
                "provider": "0x" + "0" * 24 + position.PROVIDER[2:],
                "oracle": "0x" + "0" * 24 + price.ORACLE[2:],
                "raw": words([1000, 100, 600, 8300, 8050, 2 * 10**18 + (i == 3)]),
                "code": price._code("0x6000"),
                "errors": [],
                "account": ACCOUNT,
                "head": deepcopy(observed["observations"][i]["head"]),
            }
        )
    plan = {
        "position_version": position.VERSION,
        "trace": observed["trace_report"]["plan"],
        "account": ACCOUNT,
    }
    return seal(
        {
            "position_version": position.VERSION,
            "profile": position.PROFILE,
            "plan": plan,
            "price_report": observed,
            "observations": rows,
            "classification": position.classify(rows, observed),
            "scope": position.SCOPE,
        }
    )


class PositionTests(unittest.TestCase):
    def test_six_word_exact_uints_and_no_float(self):
        values = [2**200, 1, 0, 8300, 8050, 10**18]
        self.assertEqual(list(position.decode_account(words(values)).values()), values)
        for raw in (
            "0x",
            words(values) + "00",
            words(values)[:-2],
            1,
            "0x" + "gg" * 192,
        ):
            with self.subTest(raw=str(raw)[:20]), self.assertRaises(ValueError):
                position.decode_account(raw)

    def test_only_versioned_trace_and_nonzero_account_admitted(self):
        plan = sample()["plan"]
        self.assertEqual(position.validate_plan(plan), plan)
        for account in (
            price.ZERO,
            True,
            "0x11",
            ACCOUNT.upper(),
            "https://example.com",
        ):
            bad = {**plan, "account": account}
            with self.subTest(account=account), self.assertRaises(ValueError):
                position.validate_plan(bad)
        for extra in ("selector", "pool", "rpc_url", "callback"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                position.validate_plan({**plan, extra: "anything"})

    def test_full_binding_and_exact_delta(self):
        result = sample()
        self.assertTrue(position.verify_position(result))
        self.assertEqual(
            result["classification"]["differences"]["health_factor_wad"], 1
        )
        for mutation in (
            "account",
            "profile",
            "scope",
            "delta",
            "phase",
            "raw",
            "nested",
        ):
            bad = deepcopy(result)
            if mutation == "account":
                bad["plan"]["account"] = "0x" + "aa" * 20
            elif mutation in ("profile", "scope"):
                bad[mutation] += " changed"
            elif mutation == "delta":
                bad["classification"]["differences"]["health_factor_wad"] += 1
            elif mutation == "phase":
                bad["observations"][2]["branch"] = "baseline"
            elif mutation == "raw":
                bad["observations"][1]["raw"] = "0x00"
            else:
                bad["price_report"]["trace_report"]["baseline_verified"] = False
            self.assertFalse(position.verify_position(seal(bad)))

    def test_missing_changed_initial_code_or_price_never_zero_fills(self):
        for fault in ("missing", "code", "initial", "price", "unverified"):
            result = sample()
            if fault == "missing":
                result["observations"][3]["raw"] = None
                result["observations"][3]["errors"] = [
                    {"query": "account_data", "category": "invalid_response"}
                ]
            elif fault == "code":
                result["observations"][3]["code"] = price._code("0x6001")
            elif fault == "initial":
                result["observations"][2]["raw"] = words(
                    [1001, 100, 600, 8300, 8050, 2 * 10**18]
                )
            elif fault == "price":
                result["price_report"]["classification"]["complete_price_views"] = False
            else:
                result["price_report"]["trace_report"]["baseline_verified"] = False
            value = position.classify(result["observations"], result["price_report"])
            self.assertFalse(value["complete_account_views"])
            self.assertTrue(value["unproven_reasons"])
            self.assertTrue(all(v is None for v in value["differences"].values()))

    def test_no_debt_sentinel_not_infinite_financial_improvement(self):
        result = sample()
        for row in result["observations"]:
            row["raw"] = words([1000, 0, 805, 8300, 8050, 2**256 - 1])
        result["classification"] = position.classify(
            result["observations"], result["price_report"]
        )
        self.assertTrue(position.verify_position(seal(result)))
        c = result["classification"]
        self.assertEqual(c["baseline_health_status"], "no_debt")
        self.assertIsNone(c["differences"]["health_factor_wad"])
        self.assertEqual(c["baseline"]["health_factor_wad"], 2**256 - 1)

    def test_collector_only_four_extra_fixed_reads_and_finite_errors(self):
        for failure in (None, "rpc", "abi"):

            def fault(method, params):
                if (
                    method == "eth_call"
                    and params[0]["data"] == position.PROVIDER_SELECTOR
                ):
                    return "0x" + "0" * 24 + position.PROVIDER[2:]
                if (
                    method == "eth_call"
                    and params[0]["data"] == position.ORACLE_SELECTOR
                ):
                    return "0x" + "0" * 24 + price.ORACLE[2:]
                if method == "eth_call" and params[0]["to"] == position.POOL:
                    if failure == "rpc":
                        raise RPCError("SECRET", code="timeout", method="eth_call")
                    return (
                        "0x00"
                        if failure == "abi"
                        else words([1000, 100, 600, 8300, 8050, 2 * 10**18])
                    )
                return None

            rpc = FakeRPC({"number": "0x1", "hash": "0x" + "11" * 32}, fault=fault)
            collector = position.OwnedPositionObserver(ACCOUNT)
            collector.observe(rpc, "baseline", "before", time.monotonic() + 5)
            self.assertEqual(len(rpc.calls), 13)
            self.assertEqual(
                rpc.calls[-1][1],
                [
                    {
                        "to": position.POOL,
                        "data": position.SELECTOR + "0" * 24 + ACCOUNT[2:],
                    },
                    "latest",
                ],
            )
            self.assertEqual(rpc.timeout, 10)
            self.assertNotIn("SECRET", json.dumps(collector.rows))
            self.assertEqual(collector.rows[0]["raw"] is None, failure is not None)

    def test_worker_envelope_binds_account_and_no_untrusted_hooks(self):
        from entrotter_engine.worker_protocol import (
            encode_position_request,
            execute_request,
        )

        plan = sample()["plan"]
        raw = encode_position_request(plan)
        with patch(
            "entrotter_engine.position_observations._run_position",
            return_value=sample(),
        ) as runner:
            response = execute_request(raw)
            runner.assert_called_once_with(plan, _worker_alarm=False)
        self.assertEqual(
            response["request_id"], __import__("hashlib").sha256(raw).hexdigest()
        )
        envelope = json.loads(raw)
        envelope["position"]["pool"] = position.POOL
        with self.assertRaises(ValueError):
            execute_request(json.dumps(envelope).encode())

    def test_resealed_account_head_and_diagnostic_coverage_rejected(self):
        for mutation in (
            "account",
            "head",
            "both",
            "missing",
            "duplicate",
            "private",
            "bps",
            "sentinel",
        ):
            result = sample()
            row = result["observations"][3]
            if mutation == "account":
                row["account"] = "0x" + "aa" * 20
            elif mutation == "head":
                row["head"]["timestamp"] += 1
            elif mutation == "both":
                row["errors"] = [
                    {"query": "account_data", "category": "invalid_response"}
                ]
            elif mutation == "missing":
                row["raw"] = None
            elif mutation == "duplicate":
                row["raw"] = None
                row["errors"] = [
                    {"query": "account_data", "category": "invalid_response"}
                ] * 2
            elif mutation == "private":
                row["raw"] = None
                row["errors"] = [
                    {
                        "query": "account_data",
                        "category": "rpc_error",
                        "diagnostics": {
                            "code": "timeout",
                            "method": "eth_call",
                            "url": "SECRET",
                        },
                    }
                ]
            elif mutation == "bps":
                row["raw"] = words([1, 1, 0, 10001, 8050, 10**18])
            else:
                row["raw"] = words([1, 0, 1, 8300, 8050, 0])
            self.assertFalse(position.verify_position(seal(result)), mutation)

    def test_pool_oracle_binding_mismatch_or_missing_is_unproven(self):
        for name in ("provider", "oracle"):
            for value in ("0x" + "00" * 32, None):
                result = sample()
                row = result["observations"][3]
                row[name] = value
                if value is None:
                    row["errors"] = [{"query": name, "category": "invalid_response"}]
                result["classification"] = position.classify(
                    result["observations"], result["price_report"]
                )
                self.assertTrue(position.verify_position(seal(result)))
                self.assertFalse(result["classification"]["complete_account_views"])
                self.assertIn(
                    "pool_oracle_binding_unproven",
                    result["classification"]["unproven_reasons"],
                )
                self.assertIsNone(result["classification"]["base_unit"])
                self.assertTrue(
                    all(
                        value is None
                        for value in result["classification"]["differences"].values()
                    )
                )

    def test_exact_collector_only_and_no_caller_subclass(self):
        from entrotter_engine.trace import _run_trace_native

        class Arbitrary(position.OwnedPositionObserver):
            pass

        with patch("entrotter_engine.trace.capture_source") as capture:
            with self.assertRaises(ValueError):
                _run_trace_native(sample()["plan"]["trace"], Arbitrary(ACCOUNT))
            capture.assert_not_called()

    def test_late_account_success_cannot_continue_and_restores_timeout(self):
        rpc = FakeRPC({})
        collector = position.OwnedPositionObserver(ACCOUNT)
        with patch.object(collector.price, "observe"):
            collector.price.rows = [{"head": None}]
            with patch(
                "entrotter_engine.position_observations.time.monotonic",
                side_effect=[1, 2, 3, 4, 5, 6, 7, 11],
            ):

                def call(method, params):
                    return (
                        "0x6000"
                        if method == "eth_getCode"
                        else words([1, 1, 0, 8300, 8050, 10**18])
                    )

                rpc.call = call
                with self.assertRaises(price.ObservationStopped):
                    collector.observe(rpc, "baseline", "before", 10)
        self.assertEqual(collector.rows, [])
        self.assertEqual(rpc.timeout, 10)

    def test_cli_default_native_and_stop_preserve_existing_export(self):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from entrotter_engine.__main__ import main

        for native in (False, True):
            executor = "run_position_native" if native else "run_position"
            with (
                patch(
                    "entrotter_engine.position_observations." + executor,
                    return_value=sample(),
                ) as run,
                patch(
                    "entrotter_engine.position_observations.load_plan",
                    return_value=sample()["plan"],
                ),
                patch("entrotter_engine.position_observations.write_position") as write,
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(
                    main(
                        ["trace-position", "unused", "-o", "result.json"]
                        + (["--native"] if native else [])
                    ),
                    0,
                )
                run.assert_called_once()
                write.assert_called_once()
        for code, status in (("deadline", 124), ("cancelled", 130)):
            with (
                patch(
                    "entrotter_engine.position_observations.run_position",
                    side_effect=price.ObservationStopped(code),
                ),
                patch(
                    "entrotter_engine.position_observations.load_plan",
                    return_value=sample()["plan"],
                ),
                patch("entrotter_engine.position_observations.write_position") as write,
                redirect_stderr(StringIO()),
            ):
                self.assertEqual(
                    main(["trace-position", "unused", "-o", "result.json"]), status
                )
                write.assert_not_called()

    def test_loader_duplicate_and_fifo_bound_and_atomic_quota(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            plan.write_text(json.dumps(sample()["plan"]))
            self.assertEqual(position.load_plan(plan), sample()["plan"])
            plan.write_text('{"account":"one","account":"two"}')
            with self.assertRaises(ValueError):
                position.load_plan(plan)
            plan.write_bytes(b" " * (262144 + 1))
            with self.assertRaises(ValueError):
                position.load_plan(plan)
            os.mkfifo(root / "fifo")
            with self.assertRaises(ValueError):
                position.load_plan(root / "fifo")
            target = root / "position.json"
            with patch.dict(
                os.environ, {"ENTROTTER_EXPORT_STATE_DIR": str(root / "quota")}
            ):
                position.write_position(sample(), target)
                original = target.read_bytes()
                invalid = sample()
                invalid["classification"] = {}
                with self.assertRaises(ValueError):
                    position.write_position(invalid, target)
                self.assertEqual(target.read_bytes(), original)

    def test_full_result_checker_rejects_resealed_unbound_source_change(self):
        import runpy
        import tempfile
        from contextlib import redirect_stdout
        from io import StringIO

        root = Path(__file__).resolve().parents[1]
        check = runpy.run_path(str(root / "tests_isolated/check_position_result.py"))[
            "check"
        ]
        result = position.load_position(
            root / "evidence/aave-account-impact/position.json"
        )
        with redirect_stdout(StringIO()):
            check(root / "evidence/aave-account-impact/position.json")
        changed = deepcopy(result)
        trace = changed["price_report"]["trace_report"]
        trace["source"]["block_transaction_count"] += 1
        changed["price_report"]["trace_report"] = seal(trace)
        changed["price_report"]["trace_artifact_id"] = changed["price_report"][
            "trace_report"
        ]["artifact_id"]
        changed["price_report"] = seal(changed["price_report"])
        changed = seal(changed)
        self.assertTrue(position.verify_position(changed))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(RuntimeError, "stable trace source"):
                check(path)

    def test_host_rejects_other_valid_resealed_account_and_wrong_request(self):
        import hashlib
        import os
        from test_isolated import IsolatedProtocolTests
        from entrotter_engine.isolated import run_position_isolated
        from entrotter_engine.evm import ExecutionError
        from entrotter_engine.worker_protocol import encode_position_request

        harness = IsolatedProtocolTests(
            "test_valid_response_matches_and_removes_owned_container"
        )
        harness.setUp()
        try:
            original = sample()
            changed = deepcopy(original)
            changed["plan"]["account"] = "0x" + "aa" * 20
            for row in changed["observations"]:
                row["account"] = changed["plan"]["account"]
            changed = seal(changed)
            self.assertTrue(position.verify_position(changed))
            request_id = hashlib.sha256(
                encode_position_request(original["plan"])
            ).hexdigest()
            response = harness.root / "response.json"
            for report, identity, valid in (
                (original, request_id, True),
                (changed, request_id, False),
                (original, "0" * 64, False),
            ):
                response.write_text(
                    json.dumps(
                        {
                            "worker_version": "1",
                            "request_id": identity,
                            "report": report,
                        }
                    )
                )
                with patch.dict(os.environ, {"FAKE_RESPONSE_FILE": str(response)}):
                    if valid:
                        self.assertEqual(
                            run_position_isolated(original["plan"]), original
                        )
                    else:
                        with self.assertRaises(ExecutionError):
                            run_position_isolated(original["plan"])
                harness.assert_cleanup()
        finally:
            harness.doCleanups()


if __name__ == "__main__":
    unittest.main()

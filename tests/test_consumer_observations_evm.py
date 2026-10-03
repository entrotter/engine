"""Real owned synthetic parent/transactions; no archive, wallet keys or profit."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import signal
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from entrotter_engine import consumer_observations as views
from entrotter_engine.__main__ import main
from entrotter_engine.evm import AnvilSession
from entrotter_engine.rpc import RPC
from entrotter_engine.parent_cache import ParentCache
from entrotter_engine.trace import verify_trace
import test_trace_oracle as oracle_tests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "0x3333333333333333333333333333333333333333"


def runtime(cases):
    """Tiny explicitly synthetic selector dispatcher, never used in replay repair."""
    body = bytearray.fromhex("60003560e01c")
    offsets = []
    for selector, code in cases:
        body.extend(bytes.fromhex("8063" + selector[2:] + "1461"))
        offsets.append(len(body))
        body.extend(b"\x00\x00\x57")
    body.extend(bytes.fromhex("60006000fd"))
    for offset, (_, code) in zip(offsets, cases):
        body[offset : offset + 2] = len(body).to_bytes(2, "big")
        body.extend(bytes.fromhex("5b50" + code))
    return "0x" + body.hex()


def const_return(value):
    return "7f" + value.to_bytes(32, "big").hex() + "60005260206000f3"


def price_call(oracle, offset):
    return "602060" + bytes([offset]).hex() + "6000600073" + oracle[2:] + "5afa50"


def assert_closed(node):
    if node.process is None:
        return
    if node.process.poll() is None:
        raise AssertionError("Owned Anvil guardian still alive")
    with socket.socket() as connection:
        connection.settimeout(0.2)
        if connection.connect_ex(("127.0.0.1", urlsplit(node.rpc.url).port)) == 0:
            raise AssertionError("Owned Anvil port still open")
    try:
        os.killpg(node.process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Owned Anvil process group remains")


@unittest.skipUnless(shutil.which("anvil"), "Real pinned Anvil required")
class ConsumerObservationEVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = os.getenv("ENTROTTER_TEST_EVIDENCE_DIR")
        cls.evidence = Path(output) if output else None
        cls.cleanup_records = []
        cls.fixture = json.loads(
            (ROOT / "tests/data/canonical-local-oracle-inputs.json").read_text()
        )
        fixture = cls.fixture
        cls.source = AnvilSession(trace=True)
        cls.addClassCleanup(cls.close_source)
        popen = subprocess.Popen

        def funded(command, *args, **kwargs):
            return popen(
                [*command, "--fund-accounts", *[a + ":1" for a in fixture["actors"]]],
                *args,
                **kwargs,
            )

        with patch("entrotter_engine.evm.subprocess.Popen", side_effect=funded):
            cls.source.__enter__()
        rpc = cls.source.rpc
        for raw in fixture["deployment_transactions"]:
            tx = rpc.call("eth_sendRawTransaction", [raw])
            rpc.call("evm_mine")
            if rpc.call("eth_getTransactionReceipt", [tx])["status"] != "0x1":
                raise AssertionError("Synthetic signed CREATE failed")
        # Source-only synthetic adapter installation is explicit startup state.
        # Both replay nodes use the SAME sealed parent; no replay overrides exist.
        aave_code = runtime(
            [
                (views.SELECTORS["source"], const_return(int(SOURCE, 16))),
                (views.SELECTORS["base_currency"], const_return(0)),
                (views.SELECTORS["base_unit"], const_return(views.UNIT)),
                (
                    views.SELECTORS["price"],
                    price_call(fixture["oracle"], 0) + "60206000f3",
                ),
            ]
        )
        proxy_code = runtime(
            [
                (
                    views.SELECTORS["aggregator"],
                    const_return(int(fixture["oracle"], 16)),
                ),
                (
                    views.SELECTORS["latest_round_data"],
                    price_call(fixture["oracle"], 32)
                    + "600160005260016040526002606052600160805260a06000f3",
                ),
            ]
        )
        setup_rpc = RPC(rpc.url, local=True)
        setup_rpc.call("anvil_setCode", [views.ORACLE, aave_code])
        setup_rpc.call("anvil_setCode", [SOURCE, proxy_code])
        rpc.call("evm_mine")
        for raw in fixture["raw_transactions"]:
            rpc.call("eth_sendRawTransaction", [raw])
        for method, value in [
            ("evm_setNextBlockTimestamp", fixture["target_timestamp"]),
            ("evm_setBlockGasLimit", hex(fixture["gas_limit"])),
            ("anvil_setNextBlockBaseFeePerGas", hex(fixture["base_fee"])),
            ("anvil_setCoinbase", fixture["coinbase"]),
            ("anvil_setNextBlockPrevRandao", fixture["prevrandao"]),
        ]:
            rpc.call(method, [value])
        rpc.call("evm_mine")
        block = rpc.call("eth_getBlockByNumber", ["latest", False])
        if len(block["transactions"]) != 2:
            raise AssertionError("Signed source transactions absent")
        cls.plan = {
            "trace_version": "0.1.0",
            "source": {
                "chain_id": 1,
                "block_number": int(block["number"], 16),
                "block_hash": block["hash"],
            },
            "through_index": 1,
            "skip_indices": [0],
        }
        cls.proxy = oracle_tests.ReadOnlyFaultProxy(
            rpc.url, "none", cls.plan["source"]["block_number"] - 1
        )
        cls.addClassCleanup(cls.proxy.close)
        if cls.evidence:
            cls.evidence.mkdir(exist_ok=False)
            (cls.evidence / "synthetic-source.json").write_text(
                json.dumps(
                    {
                        "scope": "Synthetic source-only genesis funding/code adapters; signed oracle CREATE/update/consumer bytes preserved; no replay state overrides or archive calls",
                        "plan": cls.plan,
                        "fixture": fixture,
                        "aave_runtime": aave_code,
                        "source_runtime": proxy_code,
                        "anvil_version": cls.source.version,
                    },
                    indent=2,
                )
                + "\n"
            )

    @classmethod
    def close_source(cls):
        cls.source.__exit__(None, None, None)
        assert_closed(cls.source)
        if cls.evidence:
            (cls.evidence / "cleanup.json").write_text(
                json.dumps(
                    {
                        "source_guardian_reaped": cls.source.process.poll() is not None,
                        "source_group_and_port_closed": True,
                        "proxy_thread_and_port_closed": not cls.proxy.thread.is_alive(),
                        "replay_runs": cls.cleanup_records,
                    },
                    indent=2,
                )
                + "\n"
            )

    def run_owned(self, *, stop=None, plan=None):
        nodes = []
        caches = []
        counters = {}
        counter_lock = threading.Lock()
        last_view = None
        original_reply = self.proxy.reply

        def reply(request):
            method = request.get("method")
            method = (
                method
                if type(method) is str and method in oracle_tests.READS
                else "other"
            )
            params = request.get("params")
            address = params[0] if isinstance(params, list) and params else None
            if isinstance(address, dict):
                address = address.get("to")
            addresses = {
                views.ORACLE: "aave_oracle",
                SOURCE: "price_source",
                self.fixture["oracle"]: "synthetic_oracle",
                self.fixture["consumer"]: "synthetic_consumer",
                **{a: "signed_actor" for a in self.fixture["actors"]},
            }
            address_class = (
                addresses.get(address.lower(), "other")
                if isinstance(address, str)
                else "none"
            )
            key = (method, address_class)

            def count(field):
                with counter_lock:
                    row = counters.setdefault(
                        key, {"requests": 0, "errors": 0, "exceptions": 0}
                    )
                    row[field] = min(4096, row[field] + 1)

            count("requests")
            try:
                result = original_reply(request)
            except Exception:
                count("exceptions")
                raise
            if isinstance(result, dict) and "error" in result:
                count("errors")
            return result

        def session(*args, **kwargs):
            node = AnvilSession(*args, **kwargs)
            nodes.append(node)
            return node

        original = views.OwnedPriceObserver.observe

        def cache(*args, **kwargs):
            owned = ParentCache(*args, **kwargs)
            caches.append(owned)
            return owned

        def observe(collector, rpc, branch, phase, deadline):
            nonlocal last_view
            last_view = [branch, phase]
            if stop == (branch, phase):
                # Real SIGTERM delivery through actual supported guard/owned nodes.
                os.kill(os.getpid(), signal.SIGTERM)
            result = original(collector, rpc, branch, phase, deadline)
            return result

        try:
            with (
                patch.dict(os.environ, {"ENTROTTER_RPC_URL": self.proxy.url}),
                patch("entrotter_engine.trace.AnvilSession", side_effect=session),
                patch("entrotter_engine.trace.ParentCache", side_effect=cache),
                patch.object(views.OwnedPriceObserver, "observe", observe),
                patch.object(self.proxy, "reply", side_effect=reply),
            ):
                result = views.run_trace_observed_native(plan or self.plan)
                if self.evidence:
                    file = self.evidence / (self._testMethodName + "-wrapper.json")
                    file.write_text(json.dumps(result, indent=2) + "\n")
                return result
        finally:
            primary = sys.exception()
            expected_stop = isinstance(primary, views.ObservationStopped) and (
                stop is not None
                or self._testMethodName
                == "test_sealing_stop_occurs_after_real_owned_cleanup"
            )
            failures = []
            checked = []

            def check(kind, function):
                try:
                    function()
                except BaseException as error:
                    failures.append((kind, error))
                    checked.append({"check": kind, "closed": False})
                else:
                    checked.append({"check": kind, "closed": True})

            for node in nodes:
                check("anvil", lambda node=node: assert_closed(node))
            for owned in caches:

                def cache_closed(owned=owned):
                    self.assertIsNotNone(owned.process.poll())
                    self.assertTrue(
                        owned.process.stdin.closed and owned.process.stdout.closed
                    )
                    with socket.socket() as connection:
                        connection.settimeout(0.2)
                        self.assertNotEqual(
                            connection.connect_ex(
                                ("127.0.0.1", urlsplit(owned.url).port)
                            ),
                            0,
                        )
                    with self.assertRaises(ProcessLookupError):
                        os.killpg(owned.process.pid, 0)

                check("cache", cache_closed)
            if primary is None or expected_stop:
                check(
                    "expected_node_count",
                    lambda: self.assertEqual(
                        len(nodes), 1 if stop and stop[0] == "baseline" else 2
                    ),
                )
            self.cleanup_records.append(
                {
                    "case": self._testMethodName,
                    "stop_phase": stop,
                    "anvil_groups_ports_reaped": sum(
                        r["closed"] for r in checked if r["check"] == "anvil"
                    ),
                    "cache_groups_ports_pipes_reaped": sum(
                        r["closed"] for r in checked if r["check"] == "cache"
                    ),
                    "cache_stats": [owned.stats for owned in caches],
                    "cleanup_checks": checked,
                    "upstream_method_address_counts": [
                        {"method": key[0], "address_class": key[1], **row}
                        for key, row in sorted(counters.items())
                    ],
                }
            )
            if primary is not None and not expected_stop or failures:
                diagnostic = {
                    "scope": "owned_synthetic_test_failure_only",
                    "primary": "observation_stopped"
                    if isinstance(primary, views.ObservationStopped)
                    else "execution_error"
                    if isinstance(primary, views.ExecutionError)
                    else "other"
                    if primary is not None
                    else "none",
                    "last_view": last_view,
                    "owned_nodes": len(nodes),
                    "owned_caches": len(caches),
                    "cleanup_checks": checked,
                    "cache_stats": [owned.stats for owned in caches],
                    "upstream": [
                        {"method": key[0], "address_class": key[1], **row}
                        for key, row in sorted(counters.items())
                    ],
                }
                try:
                    print(
                        json.dumps(diagnostic, separators=(",", ":")), file=sys.stderr
                    )
                except Exception:
                    if primary is not None:
                        primary.add_note("Secondary finite diagnostic output failure")
                    elif not failures:
                        raise
            if expected_stop and failures:
                raise AssertionError(
                    "Owned test cleanup failed during intended stop"
                ) from None
            if primary is not None:
                for kind, _ in failures:
                    primary.add_note("Secondary owned test cleanup failure: " + kind)
            elif failures:
                raise failures[0][1]

    def test_real_paired_receipts_price_effect_and_exact_original_source(self):
        result = self.run_owned()
        self.assertTrue(views.verify_observed_trace(result))
        report = result["trace_report"]
        self.assertTrue(verify_trace(report))
        self.assertTrue(report["baseline_verified"])
        self.assertEqual(
            [r["status"] for r in report["baseline"]["outcomes"]],
            ["executed", "executed"],
        )
        self.assertEqual(report["candidate"]["outcomes"][1]["receipt"]["status"], "0x0")
        self.assertEqual(
            report["candidate"]["outcomes"][1]["hash"],
            report["source"]["inputs"][1]["hash"],
        )
        self.assertTrue(result["classification"]["complete_price_views"])
        self.assertEqual(result["classification"]["baseline_price"], 20)
        self.assertEqual(result["classification"]["candidate_price"], 10)
        self.assertEqual(result["classification"]["price_difference"], -10)
        self.assertEqual(
            [int(row["raw"]["price"], 16) for row in result["observations"]],
            [10, 20, 10, 10],
        )
        self.assertEqual(
            [views._address(row["raw"]["source"]) for row in result["observations"]],
            [SOURCE] * 4,
        )
        self.assertNotIn(self.proxy.url, json.dumps(result))
        # Owned branches have not mutated upstream synthetic source value20.
        self.assertEqual(
            int(
                self.source.rpc.call(
                    "eth_call", [{"to": self.fixture["oracle"], "data": "0x"}, "latest"]
                ),
                16,
            ),
            20,
        )

    def test_actual_sigterm_before_after_and_candidate_stop_cleanup(self):
        for phase in [
            ("baseline", "before"),
            ("baseline", "after"),
            ("candidate", "after"),
        ]:
            with self.subTest(phase=phase), self.assertRaises(views.ObservationStopped):
                self.run_owned(stop=phase)

    def test_real_no_omission_reads_complete_with_zero_price_difference(self):
        result = self.run_owned(plan={**self.plan, "skip_indices": []})
        self.assertTrue(result["classification"]["complete_price_views"])
        self.assertTrue(result["classification"]["baseline_receipts_verified"])
        self.assertEqual(result["classification"]["price_difference"], 0)
        self.assertEqual(
            result["trace_report"]["baseline"]["outcomes"],
            result["trace_report"]["candidate"]["outcomes"],
        )

    def test_actual_missing_aave_code_reads_unproven_without_replay_fallback(self):
        original = self.proxy.reply

        def deny(request):
            if (
                request.get("method") == "eth_getCode"
                and request["params"][0].lower() == views.ORACLE
            ):
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32000,
                        "message": "PRIVATE synthetic code unavailable",
                    },
                }
            return original(request)

        with patch.object(self.proxy, "reply", side_effect=deny):
            result = self.run_owned()
        self.assertTrue(views.verify_observed_trace(result))
        self.assertTrue(result["trace_report"]["baseline_verified"])
        self.assertFalse(result["classification"]["complete_price_views"])
        self.assertIsNone(result["classification"]["price_difference"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_primary_baseline_observation_error_preserves_exception_and_cleanup(self):
        primary = views.ExecutionError("PRIVATE https://provider.invalid/token")
        output = StringIO()
        with (
            patch.object(views.OwnedPriceObserver, "observe", side_effect=primary),
            redirect_stderr(output),
            self.assertRaises(views.ExecutionError) as caught,
        ):
            self.run_owned()
        self.assertIs(caught.exception, primary)
        record = self.cleanup_records[-1]
        self.assertEqual(record["anvil_groups_ports_reaped"], 1)
        self.assertEqual(record["cache_groups_ports_pipes_reaped"], 1)
        self.assertEqual(
            record["cleanup_checks"],
            [{"check": "anvil", "closed": True}, {"check": "cache", "closed": True}],
        )
        diagnostic = json.loads(output.getvalue())
        self.assertEqual(diagnostic["primary"], "execution_error")
        self.assertEqual(diagnostic["last_view"], ["baseline", "before"])
        self.assertEqual(diagnostic["cleanup_checks"], record["cleanup_checks"])
        self.assertEqual(diagnostic["owned_nodes"], 1)
        self.assertEqual(diagnostic["owned_caches"], 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertNotIn("https://", output.getvalue())
        self.assertNotIn("token", output.getvalue())

    def test_sealing_stop_occurs_after_real_owned_cleanup(self):
        with (
            patch(
                "entrotter_engine.consumer_observations.seal",
                side_effect=views.ObservationStopped("cancelled"),
            ),
            self.assertRaises(views.ObservationStopped),
        ):
            self.run_owned()

    def test_real_cli_exports_verified_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "plan.json").write_text(json.dumps(self.plan))
            with (
                patch.dict(
                    os.environ,
                    {
                        "ENTROTTER_RPC_URL": self.proxy.url,
                        "ENTROTTER_EXPORT_STATE_DIR": str(path / "state"),
                    },
                ),
                redirect_stdout(StringIO()) as stdout,
            ):
                self.assertEqual(
                    main(
                        [
                            "trace-observe",
                            str(path / "plan.json"),
                            "--native",
                            "-o",
                            str(path / "result.json"),
                        ]
                    ),
                    0,
                )
            result = views.load_observed_trace(path / "result.json")
            self.assertEqual(
                json.loads(stdout.getvalue())["trace_artifact_id"],
                result["trace_report"]["artifact_id"],
            )
            self.assertEqual(result["classification"]["price_difference"], -10)


if __name__ == "__main__":
    unittest.main()

"""Fixed owned-node Aave/WETH views, separate from signed transaction replay.

Checksums bind declarations; they do not authenticate deployed code or providers.
No caller-selected addresses, selectors, callbacks or code are executed.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import threading
import time
from typing import Any

from .artifact import MAX_REPORT_BYTES, canonical, seal
from .evm import ExecutionError
from .export_budget import ExportBudget
from .rpc import FAILURE_CODES, RPC, RPCError, safe_diagnostics
from .trace import _run_trace_native, data, quantity, verify_trace

OBSERVATION_VERSION = "0.1.0"
PROFILE = "aave-v3-ethereum-weth-price"
ORACLE = "0x54586be62e3c3580375ae3723c145253060ca0c2"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ZERO = "0x" + "00" * 20
UNIT = 100_000_000
MAX_OBSERVATION_BYTES = 65536
PHASES = [
    (branch, phase)
    for branch in ("baseline", "candidate")
    for phase in ("before", "after")
]
SELECTORS = {
    "source": "0x92bf2be0",
    "price": "0xb3596f07",
    "base_currency": "0xe19f4700",
    "base_unit": "0x8c89b64f",
    "aggregator": "0x245a7bfc",
    "latest_round_data": "0xfeaf968c",
}
QUERIES = {"head", "oracle_code", "source_code", *SELECTORS}
CATEGORIES = {"rpc_error", "invalid_response", "unavailable"}
SCOPE = (
    "Owned-node read-only price views only; no signed consumer action, strategy, "
    "loan/liquidation/trade, benefit/profit, deployed-code/provider authentication, "
    "full-block/opcode/state-root proof or whole-process native sandbox."
)


class ObservationStopped(BaseException):
    """Cancellation/deadline delivery must never be normalized as an RPC timeout."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Owned consumer observation stopped")


@contextmanager
def _deadline_guard(*, _worker_alarm: bool = False):
    # The explicit native interface is synchronous and needs reliable SIGTERM
    # delivery through all owned context managers. Refuse unsafe embedding.
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        raise ExecutionError("Observed native replay requires the POSIX main thread")
    # Sample the clock first: scheduling during getitimer must shorten the
    # inherited bound conservatively, rather than moving its deadline forward.
    outer_started = time.monotonic() if _worker_alarm else None
    alarm, interval = signal.getitimer(signal.ITIMER_REAL)
    if _worker_alarm and (alarm <= 0 or interval != 0):
        raise ExecutionError("Observed worker needs its active one-shot lifetime alarm")
    if not _worker_alarm and (alarm, interval) != (0.0, 0.0):
        raise ExecutionError("Observed native replay refuses an active caller alarm")
    # Only the container entrypoint admits this path. Preserve its original
    # deadline across observation execution/cleanup; never restart 180 seconds.
    outer_deadline = outer_started + alarm if outer_started is not None else None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM)}

    def stopped(sig, frame):
        raise ObservationStopped("deadline" if sig == signal.SIGALRM else "cancelled")

    try:
        for sig in previous:
            signal.signal(sig, stopped)
        lifetime = (
            min(150, outer_deadline - time.monotonic())
            if outer_deadline is not None
            else 150
        )
        if lifetime <= 0:
            raise ObservationStopped("deadline")
        signal.setitimer(signal.ITIMER_REAL, lifetime)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if outer_deadline is not None:
            remaining = outer_deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationStopped("deadline")
            signal.setitimer(signal.ITIMER_REAL, remaining)


def _word(value: Any) -> bytes:
    return data(value, "observation ABI word", size=32)


def _address(value: Any) -> str:
    raw = _word(value)
    if raw[:12] != bytes(12):
        raise ValueError("Invalid observation address ABI")
    return "0x" + raw[12:].hex()


def _uint(value: Any) -> int:
    return int.from_bytes(_word(value), "big")


def _round(value: Any) -> dict:
    raw = data(value, "observation round ABI", size=160)
    words = [int.from_bytes(raw[i : i + 32], "big") for i in range(0, 160, 32)]
    if words[0] >= 2**80 or words[4] >= 2**80 or words[2] > words[3]:
        raise ValueError("Invalid observation round ABI")
    answer = words[1] - 2**256 if words[1] >= 2**255 else words[1]
    return dict(
        zip(
            ("round_id", "answer", "started_at", "updated_at", "answered_in_round"),
            (words[0], answer, *words[2:]),
        )
    )


def _code(value: Any) -> dict:
    raw = data(value, "owned code", limit=MAX_OBSERVATION_BYTES)
    return {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def _head(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Owned observation head is unavailable")
    return {
        "number": quantity(value.get("number"), "owned observation head"),
        "timestamp": quantity(value.get("timestamp"), "owned observation timestamp"),
        "hash": "0x" + data(value.get("hash"), "owned head hash", size=32).hex(),
    }


def _decode(name: str, value: Any) -> Any:
    if name in {"source", "base_currency", "aggregator"}:
        return _address(value)
    if name == "latest_round_data":
        return _round(value)
    return _uint(value)


class OwnedPriceObserver:
    """Internal fixed collector. Errors record finite fields; stops propagate."""

    def __init__(self):
        self.rows: list[dict] = []

    def observe(self, rpc: RPC, branch: str, phase: str, deadline: float) -> None:
        if len(self.rows) >= 4 or (branch, phase) != PHASES[len(self.rows)]:
            raise ValueError("Invalid owned observation phase order")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("Invalid owned observation deadline")
        row: dict = {
            "branch": branch,
            "phase": phase,
            "head": None,
            "raw": {},
            "code": {},
            "errors": [],
        }
        queries: list[tuple[str, str, list[Any]]] = [
            ("head", "eth_getBlockByNumber", ["latest", False]),
            ("oracle_code", "eth_getCode", [ORACLE, "latest"]),
        ]
        for name, selector in SELECTORS.items():
            payload = (
                selector + "0" * 24 + WETH[2:]
                if name in {"source", "price"}
                else selector
            )
            queries.append(
                (
                    name,
                    "eth_call",
                    [
                        {
                            "to": None
                            if name in {"aggregator", "latest_round_data"}
                            else ORACLE,
                            "data": payload,
                        },
                        "latest",
                    ],
                )
            )
        queries.insert(6, ("source_code", "eth_getCode", [None, "latest"]))
        original_timeout = rpc.timeout
        try:
            for name, method, params in queries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ObservationStopped("deadline")
                if name in {"source_code", "aggregator", "latest_round_data"}:
                    source = (
                        _address(row["raw"]["source"])
                        if "source" in row["raw"]
                        else ZERO
                    )
                    if source == ZERO:
                        row["errors"].append({"query": name, "category": "unavailable"})
                        continue
                    if method == "eth_getCode":
                        params = [source, "latest"]
                    else:
                        params = [{"to": source, "data": SELECTORS[name]}, "latest"]
                rpc.timeout = min(2.0, remaining)
                try:
                    value = rpc.call(method, params)
                    if time.monotonic() >= deadline:
                        raise ObservationStopped("deadline")
                    if name == "head":
                        row["head"] = _head(value)
                    elif name.endswith("_code"):
                        row["code"][name] = _code(value)
                    else:
                        _decode(name, value)
                        row["raw"][name] = value
                except RPCError as error:
                    row["errors"].append(
                        {
                            "query": name,
                            "category": "rpc_error",
                            "diagnostics": safe_diagnostics(error),
                        }
                    )
                except (ValueError, TypeError, KeyError):
                    row["errors"].append(
                        {"query": name, "category": "invalid_response"}
                    )
                # KeyboardInterrupt/SystemExit and signal stops intentionally escape.
        finally:
            rpc.timeout = original_timeout
        self.rows.append(row)
        if len(canonical(self.rows)) > MAX_OBSERVATION_BYTES:
            raise ExecutionError("Owned price observations exceed 64 KiB")


def _classification(rows: list[dict], report: dict) -> dict:
    reasons: set[str] = set()
    decoded = []
    for row in rows:
        values = {name: _decode(name, value) for name, value in row["raw"].items()}
        decoded.append(values)
        if row["errors"] or set(values) != set(SELECTORS) or row["head"] is None:
            reasons.add("incomplete_views")
        if values.get("source", ZERO) == ZERO:
            reasons.add("source_unavailable")
        if values.get("base_currency") != ZERO or values.get("base_unit") != UNIT:
            reasons.add("unsupported_currency_or_unit")
        feed = values.get("latest_round_data", {})
        if (
            feed.get("answer", 0) <= 0
            or feed.get("round_id", 0) <= 0
            or feed.get("updated_at", 0) <= 0
            or feed.get("answered_in_round", 0) < feed.get("round_id", 0)
            or values.get("price") != feed.get("answer")
        ):
            reasons.add("feed_price_unproven")
        head = row["head"]
        if head is None or any(
            feed.get(field, 0) > head["timestamp"]
            for field in ("started_at", "updated_at")
        ):
            reasons.add("feed_timestamp_unproven")
        if values.get("aggregator", ZERO) == ZERO:
            reasons.add("aggregator_unavailable")
        if set(row["code"]) != {"oracle_code", "source_code"} or any(
            value["bytes"] == 0 for value in row["code"].values()
        ):
            reasons.add("code_unavailable")
    if len(rows) != 4:
        reasons.add("incomplete_phases")
    if len(rows) == 4:
        if any(rows[i]["code"] != rows[0]["code"] for i in range(1, 4)):
            reasons.add("code_identity_changed")
        if any(
            value.get("aggregator") != decoded[0].get("aggregator")
            for value in decoded[1:]
        ):
            reasons.add("aggregator_changed")
        if any(
            value.get("source") != decoded[0].get("source") for value in decoded[1:]
        ):
            reasons.add("source_changed")
        if decoded[0] != decoded[2]:
            reasons.add("initial_views_differ")
        if rows[0]["head"] != rows[2]["head"]:
            reasons.add("initial_heads_differ")
        # Receipt equality is not state equivalence; actual four views are retained.
    complete = not reasons
    return {
        "complete_price_views": complete,
        "baseline_receipts_verified": report["baseline_verified"],
        "unproven_reasons": sorted(reasons),
        "baseline_price": decoded[1].get("price") if complete else None,
        "candidate_price": decoded[3].get("price") if complete else None,
        "price_difference": decoded[3]["price"] - decoded[1]["price"]
        if complete
        else None,
    }


def run_trace_observed_native(plan: dict) -> dict:
    """Explicit trusted-native, fixed-profile workflow; no default-worker fallback."""
    return _run_trace_observed(plan)


def run_trace_observed(plan: dict) -> dict:
    """Default bounded Docker execution of the fixed read-only price profile."""
    from .isolated import run_trace_observed_isolated

    return run_trace_observed_isolated(plan)


def _run_trace_observed(plan: dict, *, _worker_alarm: bool = False) -> dict:
    collector = OwnedPriceObserver()
    with _deadline_guard(_worker_alarm=_worker_alarm):
        report = _run_trace_native(plan, collector)
    result = seal(
        {
            "observation_version": OBSERVATION_VERSION,
            "profile": PROFILE,
            "trace_report": report,
            "trace_artifact_id": report["artifact_id"],
            "observations": collector.rows,
            "classification": _classification(collector.rows, report),
            "scope": SCOPE,
        }
    )
    if not verify_observed_trace(result):
        raise ExecutionError("Owned price observation binding failed")
    return result


def _validate_rows(rows: Any, report: dict) -> None:
    if (
        not isinstance(rows, list)
        or len(rows) != 4
        or len(canonical(rows)) > MAX_OBSERVATION_BYTES
    ):
        raise ValueError("Invalid observation row bound")
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "branch",
            "phase",
            "head",
            "raw",
            "code",
            "errors",
        }:
            raise ValueError("Invalid observation row shape")
        if (row["branch"], row["phase"]) != PHASES[i]:
            raise ValueError("Invalid observation phase binding")
        if not isinstance(row["raw"], dict) or not set(row["raw"]) <= set(SELECTORS):
            raise ValueError("Invalid observation ABI shape")
        for name, value in row["raw"].items():
            _decode(name, value)
        if not isinstance(row["code"], dict) or not set(row["code"]) <= {
            "oracle_code",
            "source_code",
        }:
            raise ValueError("Invalid observation code shape")
        for identity in row["code"].values():
            if (
                not isinstance(identity, dict)
                or set(identity) != {"bytes", "sha256"}
                or type(identity["bytes"]) is not int
                or not 0 <= identity["bytes"] <= MAX_OBSERVATION_BYTES
                or type(identity["sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]) is None
            ):
                raise ValueError("Invalid observation code identity")
        errors = row["errors"]
        if not isinstance(errors, list) or len(errors) > 9:
            raise ValueError("Invalid observation error bound")
        failed = set()
        for error in errors:
            if (
                not isinstance(error, dict)
                or set(error)
                not in ({"query", "category"}, {"query", "category", "diagnostics"})
                or type(error["query"]) is not str
                or error["query"] not in QUERIES
                or error["query"] in failed
                or type(error["category"]) is not str
                or error["category"] not in CATEGORIES
            ):
                raise ValueError("Invalid observation diagnostic")
            failed.add(error["query"])
            if error["category"] == "rpc_error":
                diag = error.get("diagnostics")
                expected = (
                    "eth_getBlockByNumber"
                    if error["query"] == "head"
                    else "eth_getCode"
                    if error["query"].endswith("_code")
                    else "eth_call"
                )
                if (
                    not isinstance(diag, dict)
                    or set(diag) != {"code", "method"}
                    or type(diag["code"]) is not str
                    or diag["code"] not in FAILURE_CODES
                    or diag["method"] not in {expected, None}
                ):
                    raise ValueError("Invalid observation RPC metadata")
            elif "diagnostics" in error:
                raise ValueError("Unexpected observation RPC metadata")
        available = set(row["raw"]) | set(row["code"])
        if row["head"] is not None:
            head = row["head"]
            if (
                not isinstance(head, dict)
                or set(head) != {"number", "hash", "timestamp"}
                or type(head["number"]) is not int
                or type(head["timestamp"]) is not int
                or not 0 <= head["timestamp"] < 2**64
            ):
                raise ValueError("Invalid observation head")
            data(head["hash"], "observed head hash", size=32)
            expected_number = report["source"]["parent"]["block_number"] + (i % 2)
            if head["number"] != expected_number or (
                i % 2 == 0 and head["hash"] != report["source"]["parent"]["block_hash"]
            ):
                raise ValueError("Observation parent/head binding differs")
            if (
                i % 2 == 1
                and head["timestamp"] != report["source"]["header"]["timestamp"]
            ):
                raise ValueError("Observation post timestamp differs")
            available.add("head")
        if available & failed or available | failed != QUERIES:
            raise ValueError("Observation query coverage differs")


def verify_observed_trace(result: dict) -> bool:
    """Strict wrapper/ABI/content checks, not provider or EVM authenticity proof."""
    try:
        if (
            not isinstance(result, dict)
            or set(result)
            != {
                "observation_version",
                "profile",
                "trace_report",
                "trace_artifact_id",
                "observations",
                "classification",
                "scope",
                "artifact_id",
            }
            or len(canonical(result)) > MAX_REPORT_BYTES
        ):
            return False
        if (
            result["observation_version"] != OBSERVATION_VERSION
            or result["profile"] != PROFILE
            or result["scope"] != SCOPE
            or not verify_trace(result["trace_report"])
            or result["trace_artifact_id"] != result["trace_report"]["artifact_id"]
        ):
            return False
        _validate_rows(result["observations"], result["trace_report"])
        return (
            canonical(result["classification"])
            == canonical(
                _classification(result["observations"], result["trace_report"])
            )
            and seal(result)["artifact_id"] == result["artifact_id"]
        )
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return False


def write_observed_trace(result: dict, path: str | Path) -> None:
    snapshot = json.loads(canonical(result))
    if not verify_observed_trace(snapshot):
        raise ValueError("Refusing an invalid owned observation artifact")
    raw = (
        json.dumps(snapshot, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Observed trace report exceeds 8 MiB")
    ExportBudget().write(raw, path)


def load_observed_trace(path: str | Path) -> dict:
    with os.fdopen(
        os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), "rb"
    ) as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Observed trace report must be a regular file")
        raw = source.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Observed trace report exceeds 8 MiB")
    result = json.loads(raw)
    if not verify_observed_trace(result):
        raise ValueError("Invalid owned observation artifact")
    return result

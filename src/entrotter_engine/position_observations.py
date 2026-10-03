"""Fixed Aave account views on the owned trace branches; no financial action."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

from .artifact import MAX_REPORT_BYTES, canonical, seal
from . import consumer_observations as price
from .evm import ExecutionError
from .export_budget import ExportBudget
from .rpc import FAILURE_CODES, RPC, RPCError, safe_diagnostics
from .trace import _run_trace_native, data, validate_plan as validate_trace_plan

VERSION = "0.1.0"
PROFILE = "aave-v3-ethereum-account"
# Historical January 4, 2024 address-book reference, not deployment authentication.
POOL = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
PROVIDER = "0x2f39d218133afab8f2b819b1066c7e434ad94e9e"
PROVIDER_SELECTOR = "0x0542975c"
ORACLE_SELECTOR = "0xfca513a8"
QUERIES = {"pool_code", "account_data", "provider", "oracle"}
SELECTOR = "0xbf92857c"  # getUserAccountData(address), six uint256 words.
FIELDS = (
    "total_collateral_base",
    "total_debt_base",
    "available_borrows_base",
    "liquidation_threshold_bps",
    "ltv_bps",
    "health_factor_wad",
)
SCOPE = (
    "Owned-node read-only Aave account views. Differences compare the submitted "
    "transaction-prefix branches; they do not isolate price as the sole cause. "
    "No signed consumer action, loan/liquidation execution, profit, provider or "
    "proxy-implementation authentication, full-block/state-root proof. "
    "All-account base-currency values, not token balances; WAD health factor, "
    "basis-point thresholds. Native execution has no whole-process sandbox."
)


def validate_account(account: Any) -> str:
    if (
        type(account) is not str
        or re.fullmatch(r"0x[0-9a-f]{40}", account) is None
        or account == price.ZERO
    ):
        raise ValueError("Account must be a nonzero lowercase 20-byte address")
    return account


def validate_plan(plan: Any) -> dict:
    if (
        not isinstance(plan, dict)
        or set(plan) != {"position_version", "trace", "account"}
        or plan["position_version"] != VERSION
    ):
        raise ValueError("Position plan requires exact version, trace and account")
    validate_trace_plan(plan["trace"])
    validate_account(plan["account"])
    return plan


def decode_account(raw: Any) -> dict[str, int]:
    value = data(raw, "Aave account ABI", size=192)
    values = [int.from_bytes(value[i : i + 32], "big") for i in range(0, 192, 32)]
    if values[3] > 10000 or values[4] > 10000:
        raise ValueError("Account thresholds exceed basis-point range")
    if values[1] == 0 and values[5] != 2**256 - 1:
        raise ValueError("Zero-debt health factor must retain the uint256 sentinel")
    return dict(zip(FIELDS, values))


class OwnedPositionObserver:
    """Closed collector, bound to one data-only account and four fixed queries."""

    def __init__(self, account: str):
        self.account = validate_account(account)
        self.price = price.OwnedPriceObserver()
        self.rows: list[dict] = []

    def observe(self, rpc: RPC, branch: str, phase: str, deadline: float) -> None:
        # Price collector validates phase/deadline before any RPC, using the same
        # owned connection. No mining or transaction submission occurs in this hook.
        self.price.observe(rpc, branch, phase, deadline)
        row: dict[str, Any] = {
            "branch": branch,
            "phase": phase,
            "raw": None,
            "provider": None,
            "oracle": None,
            "code": None,
            "errors": [],
            "account": self.account,
            "head": json.loads(canonical(self.price.rows[-1]["head"])),
        }
        queries = (
            ("pool_code", "eth_getCode", [POOL, "latest"], 2.0),
            (
                "provider",
                "eth_call",
                [{"to": POOL, "data": PROVIDER_SELECTOR}, "latest"],
                2.0,
            ),
            (
                "oracle",
                "eth_call",
                [{"to": PROVIDER, "data": ORACLE_SELECTOR}, "latest"],
                2.0,
            ),
            (
                "account_data",
                "eth_call",
                [
                    {"to": POOL, "data": SELECTOR + "0" * 24 + self.account[2:]},
                    "latest",
                ],
                10.0,
            ),
        )
        original_timeout = rpc.timeout
        try:
            for name, method, params, cap in queries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise price.ObservationStopped("deadline")
                rpc.timeout = min(cap, remaining)
                try:
                    value = rpc.call(method, params)
                    if time.monotonic() >= deadline:
                        raise price.ObservationStopped("deadline")
                    if name == "pool_code":
                        row["code"] = price._code(value)
                    elif name in {"provider", "oracle"}:
                        price._address(value)
                        row[name] = value
                    else:
                        decode_account(value)
                        row["raw"] = value
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
        finally:
            rpc.timeout = original_timeout
        self.rows.append(row)
        if len(canonical(self.rows)) > price.MAX_OBSERVATION_BYTES:
            raise ExecutionError("Owned account observations exceed 64 KiB")


def _health_status(value: dict | None) -> str:
    if value is None:
        return "unproven"
    if value["total_debt_base"] == 0:
        return "no_debt"
    return "below_one" if value["health_factor_wad"] < 10**18 else "at_or_above_one"


def classify(rows: list[dict], observed: dict) -> dict:
    reasons = set()
    if not observed["classification"]["complete_price_views"]:
        reasons.add("price_views_unproven")
    if not observed["trace_report"]["baseline_verified"]:
        reasons.add("baseline_receipts_unverified")
    values = [
        decode_account(row["raw"]) if row["raw"] is not None else None for row in rows
    ]
    if len(rows) != 4 or any(
        row["errors"] or row["raw"] is None or row["code"] is None for row in rows
    ):
        reasons.add("incomplete_account_views")
    if any(row["code"] is None or row["code"]["bytes"] == 0 for row in rows):
        reasons.add("pool_code_unavailable")
    if len(rows) == 4:
        if any(row["code"] != rows[0]["code"] for row in rows[1:]):
            reasons.add("pool_code_identity_changed")
        if values[0] != values[2]:
            reasons.add("initial_account_views_differ")
    if any(
        row["provider"] is None
        or price._address(row["provider"]) != PROVIDER
        or row["oracle"] is None
        or price._address(row["oracle"]) != price.ORACLE
        for row in rows
    ):
        reasons.add("pool_oracle_binding_unproven")
    complete = not reasons
    baseline = values[1] if complete else None
    candidate = values[3] if complete else None
    differences = {
        name: candidate[name] - baseline[name]
        if candidate is not None and baseline is not None
        else None
        for name in FIELDS
    }
    if (
        baseline is not None
        and candidate is not None
        and (baseline["total_debt_base"] == 0 or candidate["total_debt_base"] == 0)
    ):
        differences["health_factor_wad"] = None
    return {
        "complete_account_views": complete,
        "unproven_reasons": sorted(reasons),
        "baseline": baseline,
        "candidate": candidate,
        "differences": differences,
        "baseline_health_status": _health_status(baseline),
        "candidate_health_status": _health_status(candidate),
        "base_unit": price.UNIT if complete else None,
        "health_factor_unit": 10**18,
    }


def _validate_rows(rows: Any, plan: dict, observed: dict) -> None:
    if (
        not isinstance(rows, list)
        or len(rows) != 4
        or len(canonical(rows)) > price.MAX_OBSERVATION_BYTES
    ):
        raise ValueError("Invalid account observation bound")
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "branch",
            "phase",
            "raw",
            "provider",
            "oracle",
            "code",
            "errors",
            "account",
            "head",
        }:
            raise ValueError("Invalid account observation shape")
        if (row["branch"], row["phase"]) != price.PHASES[i]:
            raise ValueError("Invalid account observation phase")
        if row["account"] != plan["account"] or canonical(row["head"]) != canonical(
            observed["observations"][i]["head"]
        ):
            raise ValueError("Account/head binding differs")
        if row["raw"] is not None:
            decode_account(row["raw"])
        for name in ("provider", "oracle"):
            if row[name] is not None:
                price._address(row[name])
        code = row["code"]
        if code is not None and (
            not isinstance(code, dict)
            or set(code) != {"bytes", "sha256"}
            or type(code["bytes"]) is not int
            or not 0 <= code["bytes"] <= price.MAX_OBSERVATION_BYTES
            or type(code["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", code["sha256"]) is None
        ):
            raise ValueError("Invalid pool code identity")
        errors = row["errors"]
        if not isinstance(errors, list) or len(errors) > 4:
            raise ValueError("Invalid account diagnostic bound")
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
                or error["category"] not in {"rpc_error", "invalid_response"}
            ):
                raise ValueError("Invalid account diagnostic")
            failed.add(error["query"])
            if error["category"] == "rpc_error":
                diag = error.get("diagnostics")
                method = "eth_getCode" if error["query"] == "pool_code" else "eth_call"
                if (
                    not isinstance(diag, dict)
                    or set(diag) != {"code", "method"}
                    or type(diag["code"]) is not str
                    or diag["code"] not in FAILURE_CODES
                    or type(diag["method"]) not in {str, type(None)}
                    or diag["method"] not in {method, None}
                ):
                    raise ValueError("Invalid account RPC diagnostic")
            elif "diagnostics" in error:
                raise ValueError("Unexpected account RPC diagnostic")
        available = ({"pool_code"} if code is not None else set()) | (
            {"account_data"} if row["raw"] is not None else set()
        )
        available |= {name for name in ("provider", "oracle") if row[name] is not None}
        if available & failed or available | failed != QUERIES:
            raise ValueError("Account query coverage differs")


def verify_position(result: dict) -> bool:
    try:
        if (
            not isinstance(result, dict)
            or set(result)
            != {
                "position_version",
                "profile",
                "plan",
                "price_report",
                "observations",
                "classification",
                "scope",
                "artifact_id",
            }
            or len(canonical(result)) > MAX_REPORT_BYTES
            or result["position_version"] != VERSION
            or result["profile"] != PROFILE
            or result["scope"] != SCOPE
        ):
            return False
        validate_plan(result["plan"])
        if (
            not price.verify_observed_trace(result["price_report"])
            or result["price_report"]["trace_report"]["plan"] != result["plan"]["trace"]
        ):
            return False
        _validate_rows(result["observations"], result["plan"], result["price_report"])
        return (
            canonical(result["classification"])
            == canonical(classify(result["observations"], result["price_report"]))
            and seal(result)["artifact_id"] == result["artifact_id"]
        )
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return False


def _run_position(plan: dict, *, _worker_alarm: bool = False) -> dict:
    plan = json.loads(canonical(plan))
    validate_plan(plan)
    collector = OwnedPositionObserver(plan["account"])
    with price._deadline_guard(_worker_alarm=_worker_alarm):
        report = _run_trace_native(plan["trace"], collector)
    observed = seal(
        {
            "observation_version": price.OBSERVATION_VERSION,
            "profile": price.PROFILE,
            "trace_report": report,
            "trace_artifact_id": report["artifact_id"],
            "observations": collector.price.rows,
            "classification": price._classification(collector.price.rows, report),
            "scope": price.SCOPE,
        }
    )
    result = seal(
        {
            "position_version": VERSION,
            "profile": PROFILE,
            "plan": plan,
            "price_report": observed,
            "observations": collector.rows,
            "classification": classify(collector.rows, observed),
            "scope": SCOPE,
        }
    )
    if not verify_position(result):
        raise ExecutionError("Owned account observation binding failed")
    return result


def run_position_native(plan: dict) -> dict:
    return _run_position(plan)


def run_position(plan: dict) -> dict:
    from .isolated import run_position_isolated

    return run_position_isolated(plan)


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _read_json(path: str | Path, limit: int) -> Any:
    with os.fdopen(
        os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), "rb"
    ) as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Position input must be a regular file")
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Position input exceeds byte bound")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid position JSON") from error


def load_plan(path: str | Path) -> dict:
    return validate_plan(_read_json(path, 262144))


def load_position(path: str | Path) -> dict:
    value = _read_json(path, MAX_REPORT_BYTES)
    if not verify_position(value):
        raise ValueError("Invalid owned account observation artifact")
    return value


def write_position(result: dict, path: str | Path) -> None:
    snapshot = json.loads(canonical(result))
    if not verify_position(snapshot):
        raise ValueError("Refusing invalid owned account observation artifact")
    raw = (
        json.dumps(snapshot, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Position report exceeds 8 MiB")
    ExportBudget().write(raw, path)

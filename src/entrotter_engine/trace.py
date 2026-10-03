"""Canonical signed transaction-prefix replay, separate from v0.1 scenarios.

The distinct CLI/worker format does not change the v0.1 scenario/result API.
Only Ethereum mainnet's Shanghai interval and legacy/type-1/type-2 signatures are supported.
Receipts, not an entire block/state root or an alternate economy, are compared.
"""

from __future__ import annotations

import os
import json
import re
import stat
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .artifact import MAX_REPORT_BYTES, canonical, seal
from .export_budget import ExportBudget
from .evm import AnvilSession, ExecutionError
from .rpc import RPC, RPCError, RPCRejected, safe_diagnostics
from .parent_cache import ParentCache

if TYPE_CHECKING:
    from .consumer_observations import OwnedPriceObserver
    from .position_observations import OwnedPositionObserver

TRACE_VERSION = "0.1.0"
SHANGHAI_TIME = 1681338455
CANCUN_TIME = 1710338135
MAX_PREFIX = 32
MAX_INPUT_BYTES = 256 * 1024
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def quantity(value: Any, name: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(
        r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,63})", value
    ):
        raise ValueError(f"Invalid trace quantity: {name}")
    return int(value, 16)


def data(
    value: Any, name: str, *, size: int | None = None, limit: int = 65536
) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", value):
        raise ValueError(f"Invalid trace bytes: {name}")
    length = (len(value) - 2) // 2
    if length > limit or (size is not None and length != size):
        raise ValueError(f"Invalid trace byte length: {name}")
    return bytes.fromhex(value[2:])


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or set(plan) != {
        "trace_version",
        "source",
        "through_index",
        "skip_indices",
    }:
        raise ValueError(
            "Trace plan requires an exact version/source/prefix/intervention shape"
        )
    if plan["trace_version"] != TRACE_VERSION:
        raise ValueError("Unsupported trace plan version")
    source = plan["source"]
    if not isinstance(source, dict) or set(source) != {
        "chain_id",
        "block_number",
        "block_hash",
    }:
        raise ValueError("Trace source requires chain ID, block number and block hash")
    if type(source["chain_id"]) is not int or source["chain_id"] != 1:
        raise ValueError("Trace replay currently supports only Ethereum mainnet")
    if (
        type(source["block_number"]) is not int
        or not 1 <= source["block_number"] < 2**64
    ):
        raise ValueError("Invalid trace source block number")
    data(source["block_hash"], "source block hash", size=32)
    last = plan["through_index"]
    if type(last) is not int or not 0 <= last < MAX_PREFIX:
        raise ValueError("Trace prefix must contain between one and 32 transactions")
    skipped = plan["skip_indices"]
    if (
        not isinstance(skipped, list)
        or len(skipped) > MAX_PREFIX
        or any(type(i) is not int or not 0 <= i <= last for i in skipped)
    ):
        raise ValueError("Invalid skipped trace indices")
    if skipped != sorted(set(skipped)):
        raise ValueError("Skipped trace indices must be unique and sorted")
    return plan


def load_trace(path: str | Path) -> dict:
    with os.fdopen(
        os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), "rb"
    ) as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Trace plan must be a regular file")
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Trace plan exceeds 256 KiB")
    return validate_plan(json.loads(raw))


def verify_trace(report: dict) -> bool:
    """Integrity/format binding, not proof of a trustworthy node or provider."""
    if not isinstance(report, dict) or set(report) != {
        "trace_version",
        "execution_kind",
        "plan",
        "source",
        "baseline",
        "candidate",
        "baseline_verified",
        "runtime_seconds",
        "assumptions",
        "artifact_id",
    }:
        return False
    try:
        validate_plan(report["plan"])
        return (
            report["trace_version"] == TRACE_VERSION
            and report["execution_kind"] == "canonical_transaction_prefix_replay"
            and type(report["baseline_verified"]) is bool
            and isinstance(report["baseline"], dict)
            and isinstance(report["candidate"], dict)
            and report["baseline_verified"]
            == report["baseline"].get("matches_original_receipts")
            and isinstance(report["artifact_id"], str)
            and re.fullmatch(r"[0-9a-f]{64}", report["artifact_id"]) is not None
            and seal(report)["artifact_id"] == report["artifact_id"]
        )
    except (TypeError, ValueError, KeyError, RecursionError):
        return False


def write_trace(report: dict, path: str | Path) -> None:
    if not verify_trace(report):
        raise ValueError("Refusing to write an invalid transaction replay artifact")
    raw = (
        json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Trace report exceeds 8 MiB")
    ExportBudget().write(raw, path)


def run_trace(plan: dict) -> dict:
    """Bounded built-in transaction replay; no native fallback or supplied code."""
    from .isolated import run_trace_isolated

    return run_trace_isolated(plan)


def rlp(value: bytes | int | list) -> bytes:
    """Encode validated EIP transaction values; no decoder or signing key."""
    if type(value) is int:
        if not 0 <= value < 2**256:
            raise ValueError("RLP integer is outside uint256")
        return rlp(value.to_bytes((value.bit_length() + 7) // 8, "big"))
    if isinstance(value, list):
        body = b"".join(rlp(item) for item in value)
        offset = 0xC0
    elif isinstance(value, bytes):
        if len(value) == 1 and value[0] < 0x80:
            return value
        body, offset = value, 0x80
    else:
        raise ValueError("Unsupported RLP value")
    if len(body) <= 55:
        return bytes([offset + len(body)]) + body
    length = len(body).to_bytes((len(body).bit_length() + 7) // 8, "big")
    return bytes([offset + 55 + len(length)]) + length + body


def signed_transaction(tx: dict) -> str:
    """Reconstruct the original signed wire bytes from a full RPC transaction."""
    if not isinstance(tx, dict):
        raise ValueError("Trace transaction must be an object")
    kind = quantity(tx.get("type", "0x0"), "transaction type")
    if kind not in {0, 1, 2}:
        raise ValueError(
            "Unsupported trace transaction type; no signature substitution"
        )

    def q(name: str) -> int:
        return quantity(tx.get(name), name)

    destination = b"" if tx.get("to") is None else data(tx["to"], "to", size=20)
    payload = data(tx.get("input"), "transaction input")
    nonce, gas, value = q("nonce"), q("gas"), q("value")
    if not 21000 <= gas <= 30000000:
        raise ValueError("Trace transaction gas is outside supported bounds")
    scalars = []
    for name in ("r", "s"):
        raw = tx.get(name)
        if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", raw):
            raise ValueError("Invalid transaction signature scalar")
        scalars.append(int(raw, 16))
    r, s = scalars
    if not 1 <= r < SECP256K1_N or not 1 <= s <= SECP256K1_N // 2:
        raise ValueError("Invalid or noncanonical transaction signature")
    v = q("v")
    if kind == 0:
        if v not in {27, 28, 37, 38}:
            raise ValueError("Legacy signature does not match supported chain")
        if "chainId" in tx and q("chainId") != 1:
            raise ValueError("Legacy transaction chain differs from source")
        return (
            "0x"
            + rlp(
                [nonce, q("gasPrice"), gas, destination, value, payload, v, r, s]
            ).hex()
        )
    if q("chainId") != 1 or v not in {0, 1}:
        raise ValueError("Typed transaction signature chain/parity differs from source")
    if "yParity" in tx and q("yParity") != v:
        raise ValueError("Typed transaction parity fields disagree")
    access = tx.get("accessList")
    if not isinstance(access, list) or len(access) > 256:
        raise ValueError("Invalid or oversized access list")
    entries, key_count = [], 0
    for item in access:
        if (
            not isinstance(item, dict)
            or set(item) != {"address", "storageKeys"}
            or not isinstance(item["storageKeys"], list)
        ):
            raise ValueError("Invalid access-list entry")
        key_count += len(item["storageKeys"])
        if key_count > 256:
            raise ValueError("Access list exceeds 256 storage keys")
        entries.append(
            [
                data(item["address"], "access address", size=20),
                [data(key, "storage key", size=32) for key in item["storageKeys"]],
            ]
        )
    fields: list = [1, nonce]
    if kind == 1:
        fields.append(q("gasPrice"))
    else:
        priority, fee = q("maxPriorityFeePerGas"), q("maxFeePerGas")
        if priority > fee:
            raise ValueError("Priority fee exceeds maximum fee")
        fields.extend([priority, fee])
    fields.extend([gas, destination, value, payload, entries, v, r, s])
    return "0x" + (bytes([kind]) + rlp(fields)).hex()


def receipt_projection(receipt: dict) -> dict:
    """Consensus-visible receipt fields plus execution identities and fees.

    Block hash differs for a prefix; roots, withdrawals and end state are excluded.
    Logs exclude provider placement metadata but preserve ordered bytes exactly.
    """
    if not isinstance(receipt, dict):
        raise ValueError("Missing trace receipt")
    result: dict[str, Any] = {}
    for name in (
        "type",
        "status",
        "gasUsed",
        "cumulativeGasUsed",
        "effectiveGasPrice",
        "transactionIndex",
    ):
        result[name] = hex(quantity(receipt.get(name), name))
    if result["status"] not in {"0x0", "0x1"}:
        raise ValueError("Invalid trace receipt status")
    for name, length in (("transactionHash", 32), ("from", 20), ("logsBloom", 256)):
        result[name] = "0x" + data(receipt.get(name), name, size=length).hex()
    for name in ("to", "contractAddress"):
        value = receipt.get(name)
        result[name] = (
            None if value is None else "0x" + data(value, name, size=20).hex()
        )
    logs = receipt.get("logs")
    if not isinstance(logs, list) or len(logs) > 512:
        raise ValueError("Invalid or oversized trace logs")
    result["logs"] = []
    for log in logs:
        if (
            not isinstance(log, dict)
            or not isinstance(log.get("topics"), list)
            or len(log["topics"]) > 4
            or log.get("removed", False) is not False
        ):
            raise ValueError("Invalid trace log")
        result["logs"].append(
            {
                "address": "0x"
                + data(log.get("address"), "log address", size=20).hex(),
                "topics": [
                    "0x" + data(topic, "log topic", size=32).hex()
                    for topic in log["topics"]
                ],
                "data": "0x" + data(log.get("data"), "log data").hex(),
            }
        )
    if len(canonical(result)) > MAX_INPUT_BYTES:
        raise ValueError("Trace receipt exceeds 256 KiB")
    return result


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value < 0.1:
        raise ExecutionError("Canonical trace execution budget exceeded")
    return min(value, 150)


def capture_source(plan: dict, upstream: RPC, deadline: float) -> dict:
    spec = plan["source"]
    _remaining(deadline)
    if quantity(upstream.call("eth_chainId"), "upstream chain ID") != 1:
        raise ExecutionError("Trace upstream chain differs from source")
    _remaining(deadline)
    block = upstream.call("eth_getBlockByNumber", [hex(spec["block_number"]), True])
    if (
        not isinstance(block, dict)
        or quantity(block.get("number"), "block number") != spec["block_number"]
        or data(block.get("hash"), "block hash", size=32)
        != data(spec["block_hash"], "source block hash", size=32)
    ):
        raise ExecutionError("Pinned trace block is unavailable or mismatched")
    timestamp = quantity(block.get("timestamp"), "block timestamp")
    if (
        not SHANGHAI_TIME <= timestamp < CANCUN_TIME
        or quantity(block.get("difficulty"), "difficulty") != 0
    ):
        raise ExecutionError("Only the Ethereum mainnet Shanghai interval is supported")
    gas_limit = quantity(block.get("gasLimit"), "block gas limit")
    if not 21000 <= gas_limit <= 30000000:
        raise ExecutionError("Unsupported trace block gas limit")
    header = {
        "timestamp": timestamp,
        "gas_limit": gas_limit,
        "base_fee": quantity(block.get("baseFeePerGas"), "block base fee"),
        "coinbase": "0x" + data(block.get("miner"), "block coinbase", size=20).hex(),
        "prevrandao": "0x"
        + data(block.get("mixHash"), "block prevrandao", size=32).hex(),
    }
    _remaining(deadline)
    parent = upstream.call(
        "eth_getBlockByNumber", [hex(spec["block_number"] - 1), False]
    )
    if (
        not isinstance(parent, dict)
        or quantity(parent.get("number"), "parent number") != spec["block_number"] - 1
        or data(parent.get("hash"), "parent hash", size=32)
        != data(block.get("parentHash"), "expected parent hash", size=32)
        or quantity(parent.get("timestamp"), "parent timestamp") >= timestamp
    ):
        raise ExecutionError("Trace parent block is unavailable or mismatched")
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or len(transactions) <= plan["through_index"]:
        raise ExecutionError("Requested transaction prefix is unavailable")
    inputs = []
    for index, tx in enumerate(transactions[: plan["through_index"] + 1]):
        _remaining(deadline)
        if (
            not isinstance(tx, dict)
            or quantity(tx.get("transactionIndex"), "transaction index") != index
            or quantity(tx.get("blockNumber"), "transaction block")
            != spec["block_number"]
            or data(tx.get("blockHash"), "transaction block hash", size=32)
            != data(block["hash"], "block hash", size=32)
        ):
            raise ExecutionError("Trace transaction order or block binding differs")
        tx_hash = "0x" + data(tx.get("hash"), "transaction hash", size=32).hex()
        sender = "0x" + data(tx.get("from"), "sender", size=20).hex()
        raw = signed_transaction(tx)
        receipt = upstream.call("eth_getTransactionReceipt", [tx_hash])
        if (
            not isinstance(receipt, dict)
            or data(receipt.get("blockHash"), "receipt block hash", size=32)
            != data(block["hash"], "block hash", size=32)
            or quantity(receipt.get("blockNumber"), "receipt block number")
            != spec["block_number"]
        ):
            raise ExecutionError("Original trace receipt is unavailable or mismatched")
        original = receipt_projection(receipt)
        target = (
            None
            if tx.get("to") is None
            else "0x" + data(tx["to"], "transaction target", size=20).hex()
        )
        if (
            original["transactionHash"] != tx_hash
            or original["transactionIndex"] != hex(index)
            or original["from"] != sender
            or original["to"] != target
        ):
            raise ExecutionError("Original receipt does not bind to transaction")
        inputs.append(
            {
                "index": index,
                "hash": tx_hash,
                "sender": sender,
                "nonce": quantity(tx.get("nonce"), "transaction nonce"),
                "raw": raw,
                "original_receipt": original,
            }
        )
        if len(canonical(inputs)) > MAX_INPUT_BYTES:
            raise ExecutionError("Trace prefix input exceeds 256 KiB")
    return {
        "parent": {
            "chain_id": 1,
            "block_number": spec["block_number"] - 1,
            "block_hash": parent["hash"].lower(),
        },
        "header": header,
        "inputs": inputs,
        "block_transaction_count": len(transactions),
    }


def replay_branch(
    captured: dict, url: str, skipped: list[int], deadline: float
) -> dict:
    return _replay_branch(captured, url, skipped, deadline)


def _replay_branch(
    captured: dict,
    url: str,
    skipped: list[int],
    deadline: float,
    *,
    observations: OwnedPriceObserver | OwnedPositionObserver | None = None,
    branch: str = "baseline",
) -> dict:
    with AnvilSession(
        captured["parent"], url, lifetime=_remaining(deadline), trace=True
    ) as session:
        rpc = session.rpc
        if rpc is None:
            raise ExecutionError("Owned trace node was not initialized")
        head = rpc.call("eth_getBlockByNumber", ["latest", False])
        if (
            not isinstance(head, dict)
            or head.get("hash", "").lower() != captured["parent"]["block_hash"]
        ):
            raise ExecutionError("Owned trace fork does not match the original parent")
        if observations is not None:
            observations.observe(rpc, branch, "before", deadline)
        header = captured["header"]
        for method, value in (
            ("evm_setNextBlockTimestamp", header["timestamp"]),
            ("evm_setBlockGasLimit", hex(header["gas_limit"])),
            ("anvil_setCoinbase", header["coinbase"]),
            ("anvil_setNextBlockBaseFeePerGas", hex(header["base_fee"])),
            ("anvil_setNextBlockPrevRandao", header["prevrandao"]),
        ):
            _remaining(deadline)
            rpc.call(method, [value])
        expected_nonces: dict[str, int] = {}
        outcomes = []
        for tx in captured["inputs"]:
            _remaining(deadline)
            record = {"index": tx["index"], "hash": tx["hash"]}
            if tx["index"] in skipped:
                record["status"] = "skipped"
            else:
                sender = tx["sender"]
                if sender not in expected_nonces:
                    expected_nonces[sender] = quantity(
                        rpc.call("eth_getTransactionCount", [sender, "latest"]),
                        "parent nonce",
                    )
                if tx["nonce"] != expected_nonces[sender]:
                    record.update(
                        status="nonce_conflict",
                        expected_nonce=expected_nonces[sender],
                        original_nonce=tx["nonce"],
                    )
                else:
                    try:
                        actual_hash = rpc.call("eth_sendRawTransaction", [tx["raw"]])
                    except RPCRejected:
                        record["status"] = "rejected"
                    else:
                        if actual_hash != tx["hash"]:
                            raise ExecutionError(
                                "Reconstructed signature does not match original transaction hash"
                            )
                        expected_nonces[sender] += 1
                        record["status"] = "queued"
            outcomes.append(record)
        # Mining can fetch archive state for every queued transaction. Use only
        # the primitive's remaining budget, not the normal ten-second read cap.
        # The independently owned node guardian retains its absolute lifetime.
        read_timeout = rpc.timeout
        rpc.timeout = _remaining(deadline)
        try:
            rpc.call("evm_mine")
        finally:
            rpc.timeout = read_timeout
        mined = rpc.call("eth_getBlockByNumber", ["latest", False])
        if (
            not isinstance(mined, dict)
            or quantity(mined.get("number"), "mined number")
            != captured["parent"]["block_number"] + 1
        ):
            raise ExecutionError("Trace node did not mine the requested block")
        for field, expected in (
            ("timestamp", header["timestamp"]),
            ("gasLimit", header["gas_limit"]),
            ("baseFeePerGas", header["base_fee"]),
        ):
            if quantity(mined.get(field), field) != expected:
                raise ExecutionError("Mined trace header differs from canonical input")
        if (
            data(mined.get("miner"), "mined coinbase", size=20).hex()
            != header["coinbase"][2:]
            or data(mined.get("mixHash"), "mined prevrandao", size=32).hex()
            != header["prevrandao"][2:]
        ):
            raise ExecutionError("Mined trace coinbase or prevrandao differs")
        for tx, record in zip(captured["inputs"], outcomes):
            _remaining(deadline)
            if record["status"] == "queued":
                receipt = rpc.call("eth_getTransactionReceipt", [tx["hash"]])
                if receipt is None:
                    record["status"] = "not_mined"
                else:
                    projected = receipt_projection(receipt)
                    if projected["transactionHash"] != tx["hash"]:
                        raise ExecutionError(
                            "Owned trace receipt transaction hash differs"
                        )
                    record.update(
                        status="executed",
                        receipt=projected,
                        differing_fields=[
                            field
                            for field in projected
                            if projected[field] != tx["original_receipt"][field]
                        ],
                    )
        result = {
            "anvil_version": session.version,
            "outcomes": outcomes,
            "matches_original_receipts": all(
                record["status"] == "executed" and not record["differing_fields"]
                for record in outcomes
            ),
        }
        if observations is not None:
            observations.observe(rpc, branch, "after", deadline)
        return result


def run_trace_native(plan: dict) -> dict:
    """Trusted development only; no whole-process CPU/RSS sandbox or fallback."""
    return _run_trace_native(plan)


def _run_trace_native(
    plan: dict, observations: OwnedPriceObserver | OwnedPositionObserver | None = None
) -> dict:
    if observations is not None:
        from .consumer_observations import OwnedPriceObserver

        from .position_observations import OwnedPositionObserver

        if type(observations) not in {OwnedPriceObserver, OwnedPositionObserver}:
            raise ValueError("Only built-in owned observers are supported")
    plan = json.loads(canonical(plan))
    validate_plan(plan)
    url = os.environ.get("ENTROTTER_RPC_URL")
    if not url:
        raise ExecutionError(
            "Trace replay requires ENTROTTER_RPC_URL with archive state; no fallback"
        )
    deadline = time.monotonic() + 150
    started = time.monotonic()
    try:
        captured = capture_source(plan, RPC(url), deadline)
        with ParentCache(url, captured["parent"], deadline) as archive:
            if observations is None:
                baseline = replay_branch(captured, archive.url, [], deadline)
                candidate = replay_branch(
                    captured, archive.url, plan["skip_indices"], deadline
                )
            else:
                baseline = _replay_branch(
                    captured,
                    archive.url,
                    [],
                    deadline,
                    observations=observations,
                    branch="baseline",
                )
                candidate = _replay_branch(
                    captured,
                    archive.url,
                    plan["skip_indices"],
                    deadline,
                    observations=observations,
                    branch="candidate",
                )
    except RPCError as error:
        diagnostic = safe_diagnostics(error)
        code, method = diagnostic["code"], diagnostic["method"] or "unknown"
        raise ExecutionError(
            "Canonical trace RPC failed; original inputs/state may be unavailable. No fixture substitution."
            f" [rpc_code={code}; rpc_method={method}]"
        ) from None
    return seal(
        {
            "trace_version": TRACE_VERSION,
            "execution_kind": "canonical_transaction_prefix_replay",
            "plan": plan,
            "source": captured,
            "baseline": baseline,
            "candidate": candidate,
            "baseline_verified": baseline["matches_original_receipts"],
            "runtime_seconds": round(time.monotonic() - started, 6),
            "assumptions": [
                "Original signed legacy/type-1/type-2 transaction prefix only, Ethereum mainnet Shanghai rules, FIFO order; no new signatures or artificial funding.",
                "Both branches fork the pinned parent with original timestamp, coinbase, gas limit, base fee and prevrandao. Original transactions supply any in-prefix oracle updates; external responses and later transactions are not invented.",
                "A bounded experiment-local read-through bridge shares only successful exact-parent-hash state reads and hash-checked parent headers between the isolated branches. Errors, volatile reads and other blocks are not cached; no host disk cache or state repair is used.",
                "Skipping original transactions preserves every remaining signature/nonce. Nonce conflicts and rejected/unmined transactions are reported, never repaired.",
                "Owned trace nodes defer parent-state pool balance/fee/gas admission checks to ordered EVM/block execution, allowing earlier in-block funding. Accepted inputs can still remain unmined; no balance/nonce repair or sequential different-block mining is substituted.",
                "Exact projected receipts include status, gas/cumulative gas, effective price, identities, ordered log bytes and bloom. Divergence is reported; an unmatched baseline is not verified historical replay.",
                "Missing parent/account state may fail explicitly. Mining-time archive/storage errors may instead leave transactions not_mined and the baseline unverified; receipt absence alone does not identify the cause or attest parent state. No fixture state or oracle response is substituted.",
                "Block hashes/roots, withdrawals/end-block state, opcode traces, full-block replay and an alternate market are outside this transaction-prefix result.",
                "The primitive owns bounded-lifetime Anvil. Whole-process CPU/RSS isolation is supplied only by the default Docker worker; explicit native execution opts out. No upstream writes or arbitrary agent code.",
            ],
        }
    )

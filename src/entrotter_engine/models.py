"""Strict validation at the execution boundary; monetary inputs are decimal strings."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from .artifact import canonical

class ValidationError(ValueError):
    pass

def number(value: Any, name: str, *, minimum: str = "0", maximum: str = "1e30") -> Decimal:
    if not isinstance(value, str) or len(value) > 80 or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?", value) is None:
        raise ValidationError(f"{name} must be a decimal string")
    try:
        n = Decimal(value)
    except InvalidOperation as e:
        raise ValidationError(f"{name} is not a decimal") from e
    if not n.is_finite() or n < Decimal(minimum) or n > Decimal(maximum):
        raise ValidationError(f"{name} is outside the permitted range")
    if n.as_tuple().exponent < -18:
        raise ValidationError(f"{name} supports at most 18 decimal places")
    return n

def integer(v: Any, name: str, lo: int, hi: int) -> int:
    if type(v) is not int or not lo <= v <= hi:
        raise ValidationError(f"{name} must be an integer in [{lo}, {hi}]")
    return v

def keys(obj: Any, allowed: set[str], name: str) -> dict:
    if not isinstance(obj, dict):
        raise ValidationError(f"{name} must be an object")
    extra = set(obj) - allowed
    if extra:
        raise ValidationError(f"Unknown {name} fields: {', '.join(sorted(extra))}")
    return obj

def address(v: Any, name: str) -> str:
    if not isinstance(v, str) or re.fullmatch(r"0x[0-9a-fA-F]{40}", v) is None:
        raise ValidationError(f"{name} must be a 20-byte EVM address")
    return v.lower()

def policy(p: Any) -> dict:
    p = keys(p, {"type", "drawdown_trigger"}, "policy")
    if p.get("type") not in {"hold", "circuit_breaker"}:
        raise ValidationError("Only built-in hold and circuit_breaker policies are supported")
    if p["type"] == "circuit_breaker":
        number(p.get("drawdown_trigger"), "drawdown_trigger", minimum="0.001", maximum="1")
    elif "drawdown_trigger" in p:
        raise ValidationError("hold does not accept drawdown_trigger")
    return p

def validate(raw: Any) -> dict:
    try:
        if len(canonical(raw)) > 262144:
            raise ValidationError("Scenario exceeds 256 KiB")
    except (TypeError, ValueError, RecursionError) as e:
        raise ValidationError("Scenario must be finite JSON") from e
    raw = keys(raw, {"schema_version", "id", "title", "mode", "provenance", "market",
                     "baseline", "candidate", "source", "actor", "actor_balance_wei",
                     "allowed_targets", "steps", "local_contracts"}, "scenario")
    if raw.get("schema_version") != "0.1.0":
        raise ValidationError("Unsupported schema_version; expected 0.1.0")
    if not isinstance(raw.get("id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", raw["id"]):
        raise ValidationError("id must contain lowercase letters, digits and hyphens (1-64)")
    if not isinstance(raw.get("title"), str) or not 1 <= len(raw["title"]) <= 120:
        raise ValidationError("title is required (1-120 characters)")
    prov = keys(raw.get("provenance"), {"kind", "description"}, "provenance")
    if not isinstance(prov.get("description"), str) or not 1 <= len(prov["description"]) <= 2000:
        raise ValidationError("A provenance description is required")
    mode = raw.get("mode")
    if mode == "fixture":
        if any(k in raw for k in ["source", "actor", "actor_balance_wei", "allowed_targets", "steps", "local_contracts"]):
            raise ValidationError("EVM fields are not permitted in fixture mode")
        if prov.get("kind") != "synthetic":
            raise ValidationError("v0.1 fixture paths must be explicitly labelled synthetic")
        m = keys(raw.get("market"), {"prices", "initial_cash", "initial_units", "fee_bps", "slippage_bps", "symbol"}, "market")
        if not isinstance(m.get("prices"), list) or not 2 <= len(m["prices"]) <= 4096:
            raise ValidationError("prices must contain 2-4096 observations")
        for p in m["prices"]:
            number(p, "price", minimum="0.00000001", maximum="1e12")
        number(m.get("initial_cash"), "initial_cash", maximum="1e15")
        number(m.get("initial_units"), "initial_units", maximum="1e15")
        if number(m["initial_cash"], "initial_cash") == 0 and number(m["initial_units"], "initial_units") == 0:
            raise ValidationError("Portfolio must have nonzero starting value")
        integer(m.get("fee_bps"), "fee_bps", 0, 1000)
        integer(m.get("slippage_bps"), "slippage_bps", 0, 5000)
        if not isinstance(m.get("symbol"), str) or not re.fullmatch(r"[A-Z0-9_-]{1,12}", m["symbol"]):
            raise ValidationError("symbol must be 1-12 uppercase alphanumeric characters")
        policy(raw.get("baseline")); policy(raw.get("candidate"))
    elif mode in {"evm-local", "evm-fork"}:
        if any(k in raw for k in ["market", "baseline", "candidate"]):
            raise ValidationError("Fixture fields are not permitted in EVM mode")
        if prov.get("kind") != ("local-evm" if mode == "evm-local" else "historical-fork"):
            raise ValidationError("Provenance kind must match EVM mode")
        address(raw.get("actor"), "actor")
        n = number(raw.get("actor_balance_wei"), "actor_balance_wei", maximum="1e30")
        if n != n.to_integral_value() or "." in raw["actor_balance_wei"]:
            raise ValidationError("actor_balance_wei must be an integer string")
        targets = raw.get("allowed_targets")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
            raise ValidationError("allowed_targets needs 1-32 addresses")
        allow = {address(t, "target") for t in targets}
        steps = raw.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
            raise ValidationError("steps needs 1-32 slots")
        for slot in steps:
            keys(slot, {"baseline", "candidate"}, "slot")
            if set(slot) != {"baseline", "candidate"}:
                raise ValidationError("Every slot needs baseline and candidate (null = no-op)")
            for action in slot.values():
                if action is None:
                    continue
                keys(action, {"to", "value_wei", "data", "gas"}, "action")
                if address(action.get("to"), "to") not in allow:
                    raise ValidationError("Transaction target is not allowlisted")
                n = number(action.get("value_wei", "0"), "value_wei")
                if n != n.to_integral_value() or "." in action.get("value_wei", "0"):
                    raise ValidationError("value_wei must be an integer string")
                data = action.get("data", "0x")
                if not isinstance(data, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2}){0,16384}", data):
                    raise ValidationError("data must be even-length hex (maximum 16 KiB)")
                integer(action.get("gas", 21000), "gas", 21000, 2000000)
        contracts = raw.get("local_contracts", {})
        if not isinstance(contracts, dict) or len(contracts) > 8:
            raise ValidationError("local_contracts supports at most 8 entries")
        if mode == "evm-fork" and contracts:
            raise ValidationError("Code overrides are only supported in evm-local")
        for addr, code in contracts.items():
            if address(addr, "contract") not in allow:
                raise ValidationError("Local contract must be in allowed_targets")
            if not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2}){1,4096}", code):
                raise ValidationError("Local bytecode must be hex, maximum 4 KiB")
        if mode == "evm-fork":
            source = keys(raw.get("source"), {"chain_id", "block_number", "block_hash"}, "source")
            integer(source.get("chain_id"), "source.chain_id", 1, 2**53-1)
            integer(source.get("block_number"), "source.block_number", 1, 2**53-1)
            if "block_hash" in source and (not isinstance(source["block_hash"], str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", source["block_hash"])):
                raise ValidationError("source.block_hash must be a 32-byte hash")
        elif "source" in raw:
            raise ValidationError("evm-local does not take a source")
    else:
        raise ValidationError("mode must be fixture, evm-local or evm-fork")
    return raw

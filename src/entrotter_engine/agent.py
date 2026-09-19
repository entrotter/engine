"""Causal JSON-only decisions and replay. No agent code is imported or executed."""
from copy import deepcopy
import hashlib
import re
from typing import Protocol

from .artifact import canonical
from .models import ValidationError, integer, keys
from .rpc import RPCRejected

AGENT_VERSION = "0.1.0"
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 4096
MAX_RECORDING_BYTES = 3 * 1024 * 1024


class AgentError(RuntimeError):
    pass


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def decision_schema(request: dict) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["request_id", "choice", "reason"],
            "properties": {"request_id": {"type": "string", "enum": [request["request_id"]]},
                           "choice": {"type": "string", "enum": ["hold", "execute"]},
                           "reason": {"type": "string"}}}


def validate_decision(request: dict, raw: dict) -> dict:
    try:
        if len(canonical(raw)) > MAX_RESPONSE_BYTES:
            raise ValidationError("Agent response exceeds 4 KiB")
        keys(raw, {"request_id", "choice", "reason"}, "agent response")
        if set(raw) != {"request_id", "choice", "reason"} or raw["request_id"] != request["request_id"]:
            raise ValidationError("Agent response is bound to a different observation")
        if raw["choice"] not in {"hold", "execute"}:
            raise ValidationError("Agent choice must be hold or execute")
        if not isinstance(raw["reason"], str) or not 1 <= len(raw["reason"]) <= 1000:
            raise ValidationError("Agent reason must contain 1-1000 characters")
        return deepcopy(raw)
    except (ValueError, TypeError, RecursionError) as exc:
        raise AgentError("Invalid typed agent response") from exc


def observe(rpc, *, step: int, actor: str, action: dict, tokens: list[dict],
            balances: dict, previous: list[dict], gas_remaining: int) -> dict:
    """Only current node reads, current proposal, and completed actions reach policy.

    Intentionally does not accept a scenario, title, future steps, source date or
    future prices. A preflight is a current-state eth_call, not a forecast.
    """
    head = rpc.call("eth_getBlockByNumber", ["latest", False])
    tx = {"from": actor, "to": action["to"], "data": action.get("data", "0x"),
          "value": hex(int(action.get("value_wei", "0"))), "gas": hex(action.get("gas", 21000))}
    try:
        result = rpc.call("eth_call", [tx, "latest"])
        if not isinstance(result, str) or re.fullmatch(r"0x(?:[0-9a-fA-F]{2}){0,4096}", result) is None:
            raise AgentError("Agent preflight result must be hex bytes, maximum 4 KiB")
        preflight = {"status": "success", "return_data": result}
    except RPCRejected:
        preflight = {"status": "rejected", "return_data": None}
    request = {
        "agent_version": AGENT_VERSION,
        "observation": {"step": step, "local_block_number": int(head["number"], 16),
                        "local_block_hash": head["hash"], "timestamp": int(head["timestamp"], 16),
                        "actor": actor, "local_chain_id": int(rpc.call("eth_chainId", []), 16),
                        "native_balance_wei": str(int(rpc.call("eth_getBalance", [actor, "latest"]), 16)),
                        "tokens": [{**t, "balance_raw": balances[t["address"].lower()]} for t in tokens],
                        "completed_actions": [{"step": x["step"], "status": x["status"],
                                               "gas_used": x["gas_used"]} for x in previous]},
        "proposed_action": deepcopy(action), "preflight": preflight,
        "limits": {"remaining_requested_gas": gas_remaining,
                   "max_response_bytes": MAX_RESPONSE_BYTES},
        "choices": {"execute": "Execute exactly this allowlisted proposal on the owned local node",
                    "hold": "Mine this slot without a transaction"}}
    if len(canonical(request)) > MAX_REQUEST_BYTES:
        raise AgentError("Causal observation exceeds 64 KiB")
    request["request_id"] = digest(request)
    return request


class DecisionProvider(Protocol):
    metadata: dict

    def decide(self, request: dict) -> dict: ...


class RiskPolicy:
    metadata = {"provider": "builtin", "model": "preflight-risk-v1",
                "deterministic": True, "seed": None, "cost_usd": "0"}

    def decide(self, request: dict) -> dict:
        execute = (request["preflight"]["status"] == "success" and
                   request["proposed_action"].get("gas", 21000) <= request["limits"]["remaining_requested_gas"])
        return {"request_id": request["request_id"], "choice": "execute" if execute else "hold",
                "reason": "Current-state preflight and requested gas fit the policy" if execute else
                          "Current-state preflight or requested gas exceeds the policy"}


class ReplayPolicy:
    def __init__(self, recording: dict):
        try:
            keys(recording, {"agent_version", "provider", "exchanges"}, "agent recording")
            if (len(canonical(recording)) > MAX_RECORDING_BYTES or
                    recording.get("agent_version") != AGENT_VERSION or
                    not isinstance(recording.get("provider"), dict) or
                    not isinstance(recording.get("exchanges"), list) or
                    not 1 <= len(recording["exchanges"]) <= 32):
                raise ValueError("Unsupported recording")
            for exchange in recording["exchanges"]:
                if not isinstance(exchange, dict) or set(exchange) != {"request", "response"}:
                    raise ValueError("Invalid exchange")
                request = exchange["request"]
                if not isinstance(request, dict) or len(canonical(request)) > MAX_REQUEST_BYTES + 128:
                    raise ValueError("Invalid observation")
                if request.get("request_id") != digest({k: v for k, v in request.items() if k != "request_id"}):
                    raise ValueError("Invalid observation digest")
                validate_decision(request, exchange["response"])
        except (ValueError, TypeError, RecursionError) as exc:
            raise AgentError("Invalid bounded agent recording") from exc
        self.recording = deepcopy(recording)
        self.metadata = deepcopy(recording["provider"])
        self.index = 0

    def decide(self, request: dict) -> dict:
        if self.index >= len(self.recording["exchanges"]):
            raise AgentError("Recording exhausted")
        exchange = self.recording["exchanges"][self.index]
        if canonical(request) != canonical(exchange["request"]):
            raise AgentError("Recorded observation diverged; refusing action replay")
        self.index += 1
        return validate_decision(request, exchange["response"])

    def finish(self):
        if self.index != len(self.recording["exchanges"]):
            raise AgentError("Unused decisions remain in the recording")


class AgentController:
    def __init__(self, provider: DecisionProvider, decision_steps: list[int], *, max_requested_gas: int = 2000000):
        if not isinstance(decision_steps, list) or not 1 <= len(decision_steps) <= 32:
            raise AgentError("Select 1-32 decision steps")
        for step in decision_steps:
            integer(step, "decision step", 0, 31)
        if len(set(decision_steps)) != len(decision_steps):
            raise AgentError("Decision steps must be unique")
        integer(max_requested_gas, "agent gas budget", 21000, 64000000)
        self.provider, self.steps = provider, set(decision_steps)
        self.remaining_gas = max_requested_gas
        self.exchanges = []
        self.seen = set()
        self.started = False

    def start(self):
        if self.started:
            raise AgentError("Controller is single-use; create a fresh controller for replay")
        self.started = True

    def choose(self, rpc, *, step, actor, action, tokens, balances, previous):
        if step not in self.steps:
            return action, None
        if step in self.seen:
            raise AgentError("Decision step was already consumed")
        self.seen.add(step)
        if action is None:
            raise AgentError("A selected decision step must propose an action")
        request = observe(rpc, step=step, actor=actor, action=action, tokens=tokens,
                          balances=balances, previous=previous, gas_remaining=self.remaining_gas)
        response = validate_decision(request, self.provider.decide(deepcopy(request)))
        requested = action.get("gas", 21000)
        if response["choice"] == "execute" and requested > self.remaining_gas:
            raise AgentError("Agent action exceeds the requested-gas budget")
        if response["choice"] == "execute":
            self.remaining_gas -= requested
        exchange = {"request": request, "response": response}
        self.exchanges.append(exchange)
        return action if response["choice"] == "execute" else None, response

    def recording(self):
        if len(self.exchanges) != len(self.steps):
            raise AgentError("Not every requested decision step was reached")
        if isinstance(self.provider, ReplayPolicy):
            self.provider.finish()
        recording = {"agent_version": AGENT_VERSION, "provider": deepcopy(self.provider.metadata),
                     "exchanges": deepcopy(self.exchanges)}
        ReplayPolicy(recording)  # Enforce the same bounds on generated and imported records.
        return recording

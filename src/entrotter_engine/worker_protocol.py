"""Closed JSON transport for built-in risk/replay; never imports supplied providers."""

from hashlib import sha256
import json

from .agent import AgentController, ReplayPolicy, RiskPolicy, validate_selection
from .artifact import canonical
from .models import keys, validate

WORKER_VERSION = "1"
MAX_SCENARIO_INPUT = 262144
MAX_AGENT_INPUT = 4 * 1024 * 1024


def agent_controller(scenario: dict, configuration: dict) -> AgentController:
    keys(
        configuration,
        {"decision_steps", "max_requested_gas", "recording"},
        "agent configuration",
    )
    if set(configuration) != {"decision_steps", "max_requested_gas", "recording"}:
        raise ValueError("Agent configuration needs steps, gas budget and recording")
    recording = configuration["recording"]
    provider = RiskPolicy() if recording is None else ReplayPolicy(recording)
    controller = AgentController(
        provider,
        configuration["decision_steps"],
        max_requested_gas=configuration["max_requested_gas"],
    )
    validate_selection(scenario, controller)
    return controller


def encode_agent_request(scenario: dict, configuration: dict) -> bytes:
    validate(scenario)
    if len(canonical(scenario)) > MAX_SCENARIO_INPUT:
        raise ValueError("Agent scenario exceeds 256 KiB")
    agent_controller(scenario, configuration)
    payload = canonical(
        {"worker_version": WORKER_VERSION, "scenario": scenario, "agent": configuration}
    )
    if len(payload) > MAX_AGENT_INPUT:
        raise ValueError("Agent worker request exceeds 4 MiB")
    return payload


def execute_request(raw: bytes) -> dict:
    """Worker-only dispatcher; validates all data before native execution."""
    from .runner import run_agent_native, run_native

    if not raw or len(raw) > MAX_AGENT_INPUT:
        raise ValueError("Worker input exceeds 4 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Worker request must be an object")
    if "worker_version" not in value:
        if len(raw) > MAX_SCENARIO_INPUT:
            raise ValueError("Scenario input exceeds 256 KiB")
        validate(value)
        return run_native(value)
    if (
        set(value) != {"worker_version", "scenario", "agent"}
        or value["worker_version"] != WORKER_VERSION
    ):
        raise ValueError("Unsupported agent worker envelope")
    scenario = value["scenario"]
    validate(scenario)
    if len(canonical(scenario)) > MAX_SCENARIO_INPUT:
        raise ValueError("Agent scenario exceeds 256 KiB")
    controller = agent_controller(scenario, value["agent"])
    return {
        "worker_version": WORKER_VERSION,
        "request_id": sha256(raw).hexdigest(),
        "report": run_agent_native(scenario, controller),
    }

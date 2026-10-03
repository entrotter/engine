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


def encode_trace_request(plan: dict) -> bytes:
    from .trace import validate_plan

    snapshot = json.loads(canonical(plan))
    validate_plan(snapshot)
    payload = canonical({"worker_version": WORKER_VERSION, "trace": snapshot})
    if len(payload) > MAX_SCENARIO_INPUT:
        raise ValueError("Trace worker request exceeds 256 KiB")
    return payload


def encode_observed_trace_request(plan: dict) -> bytes:
    from .consumer_observations import PROFILE

    snapshot = json.loads(encode_trace_request(plan))["trace"]
    payload = canonical(
        {
            "worker_version": WORKER_VERSION,
            "trace": snapshot,
            "observation_profile": PROFILE,
        }
    )
    if len(payload) > MAX_SCENARIO_INPUT:
        raise ValueError("Observed trace worker request exceeds 256 KiB")
    return payload


def encode_position_request(plan: dict) -> bytes:
    from .position_observations import PROFILE, validate_plan

    snapshot = json.loads(canonical(plan))
    validate_plan(snapshot)
    payload = canonical(
        {
            "worker_version": WORKER_VERSION,
            "position": snapshot,
            "position_profile": PROFILE,
        }
    )
    if len(payload) > MAX_SCENARIO_INPUT:
        raise ValueError("Position worker request exceeds 256 KiB")
    return payload


def execute_request(raw: bytes, *, _worker_alarm: bool = False) -> dict:
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
        set(value) == {"worker_version", "position", "position_profile"}
        and value["worker_version"] == WORKER_VERSION
    ):
        from .position_observations import (
            PROFILE,
            validate_plan,
            _run_position,
            _unique_object,
        )

        value = json.loads(raw, object_pairs_hook=_unique_object)

        if len(raw) > MAX_SCENARIO_INPUT or value["position_profile"] != PROFILE:
            raise ValueError("Invalid bounded position worker profile")
        validate_plan(value["position"])
        return {
            "worker_version": WORKER_VERSION,
            "request_id": sha256(raw).hexdigest(),
            "report": _run_position(value["position"], _worker_alarm=_worker_alarm),
        }
    if (
        set(value) == {"worker_version", "trace", "observation_profile"}
        and value["worker_version"] == WORKER_VERSION
    ):
        from .consumer_observations import PROFILE, _run_trace_observed
        from .trace import validate_plan

        if value["observation_profile"] != PROFILE:
            raise ValueError("Unsupported observation profile")
        if len(raw) > MAX_SCENARIO_INPUT:
            raise ValueError("Observed trace worker request exceeds 256 KiB")
        validate_plan(value["trace"])
        return {
            "worker_version": WORKER_VERSION,
            "request_id": sha256(raw).hexdigest(),
            "report": _run_trace_observed(value["trace"], _worker_alarm=_worker_alarm),
        }
    if (
        set(value) == {"worker_version", "trace"}
        and value["worker_version"] == WORKER_VERSION
    ):
        from .trace import validate_plan, run_trace_native

        if len(raw) > MAX_SCENARIO_INPUT:
            raise ValueError("Trace worker request exceeds 256 KiB")
        validate_plan(value["trace"])
        return {
            "worker_version": WORKER_VERSION,
            "request_id": sha256(raw).hexdigest(),
            "report": run_trace_native(value["trace"]),
        }
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

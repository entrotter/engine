from __future__ import annotations
import json
import os
import stat
from pathlib import Path
from .models import validate
from .fixture import run_fixture
from .evm import run_evm


def run(scenario: dict) -> dict:
    """Execute through the configured bounded worker, with no native fallback."""
    from .isolated import run_isolated

    return run_isolated(scenario)


def run_native(scenario: dict) -> dict:
    """Trusted development/container primitive; no whole-process resource sandbox."""
    validate(scenario)
    # Copy to prevent a caller modifying the schema mid-experiment.
    scenario = json.loads(json.dumps(scenario, allow_nan=False))
    return run_fixture(scenario) if scenario["mode"] == "fixture" else run_evm(scenario)


def load(path: str | Path) -> dict:
    # Open nonblocking before inspecting the descriptor so a FIFO replacement
    # cannot wait indefinitely. Read only the admitted bytes, not the entire file.
    with os.fdopen(
        os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)), "rb"
    ) as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Scenario must be a regular file")
        data = source.read(262144 + 1)
    if len(data) > 262144:
        raise ValueError("Scenario exceeds 256 KiB")
    return validate(json.loads(data))


def run_agent(
    scenario: dict,
    *,
    decision_steps: list[int],
    recording: dict | None = None,
    max_requested_gas: int = 2000000,
) -> dict:
    """Bounded built-in risk decisions or exact recorded replay; no supplied code."""
    from .isolated import run_agent_isolated

    return run_agent_isolated(
        scenario,
        {
            "decision_steps": decision_steps,
            "recording": recording,
            "max_requested_gas": max_requested_gas,
        },
    )


def run_agent_native(scenario: dict, controller) -> dict:
    """Explicit trusted provider API; caller code has no CPU/RSS/egress sandbox."""
    from .agent import validate_selection

    validate(scenario)
    validate_selection(scenario, controller)
    snapshot = json.loads(json.dumps(scenario, allow_nan=False))
    controller.start()
    return run_evm(snapshot, controller=controller)

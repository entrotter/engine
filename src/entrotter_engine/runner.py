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

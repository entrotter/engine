from __future__ import annotations
import json
from pathlib import Path
from .models import validate
from .fixture import run_fixture
from .evm import run_evm


def run(scenario: dict) -> dict:
    validate(scenario)
    # Copy to prevent a caller modifying the schema mid-experiment.
    scenario = json.loads(json.dumps(scenario, allow_nan=False))
    return run_fixture(scenario) if scenario["mode"] == "fixture" else run_evm(scenario)


def load(path: str | Path) -> dict:
    data = Path(path).read_bytes()
    if len(data) > 262144:
        raise ValueError("Scenario exceeds 256 KiB")
    return validate(json.loads(data))

"""Canonical, content-addressed result artifacts. No claim of proof of correctness."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any

VERSION = "0.1.0"

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")

def seal(payload: dict) -> dict:
    body = {k: v for k, v in payload.items() if k != "artifact_id"}
    return {**body, "artifact_id": hashlib.sha256(canonical(body)).hexdigest()}

def verify(report: dict) -> bool:
    if not isinstance(report, dict) or report.get("schema_version") != VERSION:
        return False
    supplied = report.get("artifact_id")
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return False
    try:
        return seal(report)["artifact_id"] == supplied
    except (TypeError, ValueError):
        return False

def write_report(report: dict, path: str | Path) -> None:
    if not verify(report):
        raise ValueError("Refusing to write an invalid artifact")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement avoids a partially written JSON file.
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n")
    temp.replace(path)

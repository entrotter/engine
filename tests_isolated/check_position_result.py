"""Check the full current account result against the retained original execution."""

import json
from pathlib import Path
import sys
from entrotter_engine.position_observations import load_position

ROOT = Path(__file__).resolve().parents[1]


def check(path):
    fresh = load_position(path)
    retained = load_position(ROOT / "evidence/aave-account-impact/position.json")
    trace = fresh["price_report"]["trace_report"]
    stable_fresh = {
        key: value
        for key, value in trace.items()
        if key not in {"artifact_id", "runtime_seconds"}
    }
    stable_retained = {
        key: value
        for key, value in retained["price_report"]["trace_report"].items()
        if key not in {"artifact_id", "runtime_seconds"}
    }
    if stable_fresh != stable_retained:
        raise RuntimeError(
            "Complete stable trace source, assumptions or outcomes differ"
        )
    original = json.loads(
        (ROOT / "evidence/aave-consumer-price/native-006/report.json").read_text()
    )
    plan = json.loads((ROOT / "tests/data/aave-account-prefix.json").read_text())
    if (
        fresh["plan"] != plan
        or trace["baseline"]["outcomes"] != original["baseline"]["outcomes"][:13]
    ):
        raise RuntimeError("Exact input or thirteen original baseline receipts differ")
    if not trace["baseline_verified"] or [
        x["status"] for x in trace["candidate"]["outcomes"]
    ] != ["executed"] * 12 + ["skipped"]:
        raise RuntimeError("Historical baseline or unchanged omission policy differs")
    if (
        trace["candidate"]["outcomes"]
        != retained["price_report"]["trace_report"]["candidate"]["outcomes"]
    ):
        raise RuntimeError("Complete remaining signed receipt outcomes differ")
    if (
        not fresh["classification"]["complete_account_views"]
        or fresh["classification"] != retained["classification"]
    ):
        raise RuntimeError(
            "Complete six-field account classification differs; no substitute"
        )
    if (
        fresh["observations"] != retained["observations"]
        or fresh["price_report"]["observations"]
        != retained["price_report"]["observations"]
    ):
        raise RuntimeError(
            "Full raw ABI, heads, errors, pool/configuration/price views differ"
        )
    if (
        fresh["price_report"]["classification"]
        != retained["price_report"]["classification"]
    ):
        raise RuntimeError("Exact original price classification differs")
    print(
        json.dumps(
            {
                "artifact_id": fresh["artifact_id"],
                "trace_runtime_seconds": trace["runtime_seconds"],
                "verified_original_receipts": 13,
                "classification": fresh["classification"],
            }
        )
    )


if __name__ == "__main__":
    check(sys.argv[1])

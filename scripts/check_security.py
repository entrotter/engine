#!/usr/bin/env python3
"""Run every Bandit rule and require an exact, reasoned review of each finding.

Reports retain accepted findings. No rule/severity suppression or nosec bypass is
used; changed, new, missing and unreviewed findings all fail this gate.
"""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(finding):
    return {
        "file": Path(finding["filename"]).as_posix().removeprefix("./"),
        "test_id": finding["test_id"],
        "line": finding["line_number"],
        "code_sha256": hashlib.sha256(finding["code"].encode()).hexdigest(),
    }


def evaluate(report, reviews):
    if report.get("errors") or not report.get("metrics", {}).get("_totals", {}).get(
        "loc", 0
    ):
        raise ValueError("Scanner failed or did not inspect source")
    if report["metrics"]["_totals"].get("skipped_tests", 0):
        raise ValueError("Scanner skipped tests")
    actual = [fingerprint(item) for item in report["results"]]
    expected = []
    for review in reviews["findings"]:
        if not isinstance(review.get("reason"), str) or len(review["reason"]) < 40:
            raise ValueError("Every accepted finding needs a concrete review rationale")
        expected.append(
            {key: review[key] for key in ["file", "test_id", "line", "code_sha256"]}
        )

    def normalize(items):
        return sorted(json.dumps(item, sort_keys=True) for item in items)

    if normalize(actual) != normalize(expected):
        raise ValueError(
            "Security findings changed; inspect full report and review each finding"
        )
    return len(actual)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".quality/bandit.json"))
    args = parser.parse_args()
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "--ignore-nosec",
            "-r",
            "src",
            "scripts",
            "-f",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode not in (0, 1):
        raise RuntimeError("Bandit failed to run")
    report = json.loads(process.stdout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    reviews = json.loads((ROOT / "security-reviewed.json").read_text())
    if version("bandit") != reviews["scanner_version"]:
        raise ValueError("Bandit version changed; rerun and review findings")
    expected_files = {
        p.relative_to(ROOT).as_posix()
        for directory in [ROOT / "src", ROOT / "scripts"]
        for p in directory.rglob("*.py")
    }
    scanned_files = set(report.get("metrics", {})) - {"_totals"}
    if expected_files != scanned_files:
        raise ValueError("Bandit did not scan every production source and script")
    source_hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in expected_files
    }
    if source_hashes != reviews["source_sha256"]:
        raise ValueError(
            "Production sources changed; refresh the security review with the full scan"
        )
    count = evaluate(report, reviews)
    print(
        f"Full Bandit scan completed: {count} explicitly reviewed findings retained in {args.output}"
    )


if __name__ == "__main__":
    main()

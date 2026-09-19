#!/usr/bin/env python3
"""Require every declared Python runtime/build dependency in the audited lock."""

import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def canonicalize_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def check(project, lock_text):
    locked = {
        canonicalize_name(name): version
        for name, version in re.findall(
            r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^\s\\]+)",
            lock_text,
            re.MULTILINE,
        )
    }
    if not locked or "--hash=sha256:" not in lock_text:
        raise ValueError("Expected a complete hashed dependency lock")
    optional = project["project"].get("optional-dependencies", {})
    declared = (
        project["project"].get("dependencies", []) + project["build-system"]["requires"]
    )
    declared += [item for group in optional.values() for item in group]
    for raw in declared:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", raw)
        if not match or locked.get(canonicalize_name(match[1])) != match[2]:
            raise ValueError(
                "Every runtime/build dependency must be exactly pinned in the audited lock"
            )
    return {
        "runtime": project["project"].get("dependencies", []),
        "build": project["build-system"]["requires"],
        "optional_runtime": optional,
        "audited_locked_packages": len(locked),
    }


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scope = check(project, (ROOT / "requirements-quality.txt").read_text())
    output = ROOT / ".quality/dependency-scope.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scope, indent=2) + "\n")
    print(json.dumps(scope))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify the pinned base signature and scan every detected worker package.

No vulnerability suppressions are accepted. Raw findings and detected inventories
remain in the output even on failure. This is not a complete Anvil binary audit.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

from entrotter_engine.isolated import client

ROOT = Path(__file__).resolve().parents[1]
TRIVY_VERSION = "0.74.0"
COSIGN_VERSION = "3.1.3"
IDENTITY = "https://github.com/chainguard-images/images/.github/workflows/release.yaml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
MAX_TOOL_BYTES = 256 * 1024 * 1024
TOOLS = {
    ("Darwin", "arm64"): (
        "macOS-ARM64",
        "1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11",
        "darwin-arm64",
        "5cf948c2f4dfe59687bdd0b8523709067383e03982cc543475c8a7dc70e92a76",
    ),
    ("Darwin", "x86_64"): (
        "macOS-64bit",
        "472816f6888dda689d075c30254d4210b4d1035acf365aa72332f584c2f60485",
        "darwin-amd64",
        "2347488e5d5b25336644024dfeca5601b190e91197a71a917bda44744aff106c",
    ),
    ("Linux", "x86_64"): (
        "Linux-64bit",
        "2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a",
        "linux-amd64",
        "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71",
    ),
    ("Linux", "aarch64"): (
        "Linux-ARM64",
        "b94ce1976bbf3c15b514b605ee88be7c6d94a29be2302847ff01cb794d47aad5",
        "linux-arm64",
        "c5d324e091826b0d7a78eb16fef316450b4eb9aaec045611c08ba06f5e73220a",
    ),
}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def verified_download(url, expected, target, supplied=None):
    if supplied:
        if not supplied.is_file() or supplied.stat().st_size > MAX_TOOL_BYTES:
            raise ValueError("Supplied tool must be a bounded regular file")
        shutil.copyfile(supplied, target)
    else:
        with urlopen(url, timeout=60) as response, target.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_TOOL_BYTES:
                    raise ValueError("Tool download exceeds size limit")
                output.write(chunk)
    if digest(target) != expected:
        raise ValueError("Tool release digest mismatch")


def evaluate(report, expected_image, database, now=None):
    now = now or datetime.now(timezone.utc)
    updated = datetime.fromisoformat(database["UpdatedAt"])
    next_update = datetime.fromisoformat(database["NextUpdate"])
    if (
        database["Version"] != 2
        or updated.tzinfo is None
        or next_update.tzinfo is None
        or updated > now + timedelta(minutes=5)
        or now - updated > timedelta(days=1)
        or next_update <= now
        or next_update <= updated
    ):
        raise ValueError("Vulnerability database is stale or invalid")
    if (
        report.get("SchemaVersion") != 2
        or report.get("Trivy", {}).get("Version") != TRIVY_VERSION
    ):
        raise ValueError("Unexpected scanner report format/version")
    metadata = report.get("Metadata", {})
    if (
        metadata.get("ImageID") != expected_image
        or report.get("ArtifactType") != "container_image"
    ):
        raise ValueError("Scanner report is not bound to the requested image")
    if metadata.get("OS", {}).get("Family") != "wolfi" or metadata.get("OS", {}).get(
        "Eosl"
    ):
        raise ValueError("Expected supported Wolfi OS inventory")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Scanner returned no package inventories")
    inventories = []
    findings = []
    os_packages = set()
    for result in results:
        packages = result.get("Packages", [])
        if not isinstance(packages, list):
            raise ValueError("Invalid package inventory")
        for package in packages:
            if not package.get("Name") or not package.get("Version"):
                raise ValueError("Package identity/version missing")
            if result.get("Class") == "os-pkgs" and result.get("Type") == "wolfi":
                os_packages.add(package["Name"])
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            raise ValueError("Invalid vulnerability inventory")
        for finding in vulnerabilities:
            if not finding.get("VulnerabilityID") or not finding.get("PkgName"):
                raise ValueError("Invalid finding identity")
        findings.extend(vulnerabilities)
        inventories.append(
            {
                "type": result.get("Type"),
                "class": result.get("Class"),
                "packages": len(packages),
                "findings": len(vulnerabilities),
            }
        )
    required = {
        "python-3.14",
        "python-3.14-base",
        "glibc-2.44",
        "libssl3",
        "ca-certificates-bundle",
    }
    if not required.issubset(os_packages):
        raise ValueError("Expected interpreter/libc/TLS package coverage is missing")
    return {
        "status": "findings" if findings else "passed",
        "image_id": expected_image,
        "inventories": inventories,
        "vulnerability_count": len(findings),
        "database_updated_at": database["UpdatedAt"],
        "database_next_update": database["NextUpdate"],
        "policy": "Every detected vulnerability, including unfixed and unknown severity, fails; no suppression files or VEX",
        "limitations": [
            "Only detected OS/language packages are covered, not proof of absence of vulnerabilities",
            "Native Anvil dependencies without embedded inventory remain outside this scan",
            "Docker daemon, host kernel/VM and arbitrary user code are not audited",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".quality/trivy-cache"))
    parser.add_argument(
        "--trivy-archive",
        type=Path,
        help="Optional digest-verified local release archive",
    )
    parser.add_argument(
        "--cosign-binary",
        type=Path,
        help="Optional digest-verified local release binary",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = args.cache.resolve()
    manifest = json.loads(args.manifest.read_text())
    image = manifest["image_id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Audit requires an immutable local image ID")
    sources = {p.name: digest(p) for p in (ROOT / "src/entrotter_engine").glob("*.py")}
    sources["Dockerfile"] = digest(ROOT / "container/Dockerfile")
    if sources != manifest["source_files"]:
        raise ValueError("Worker manifest does not match this checkout")
    source_digest = hashlib.sha256(
        json.dumps(sources, sort_keys=True).encode()
    ).hexdigest()
    if source_digest != manifest["source_digest"]:
        raise ValueError("Invalid worker source digest")
    base = (ROOT / "container/Dockerfile").read_text().splitlines()[0].split()[1]
    if base != manifest["base_image"] or not re.fullmatch(
        r"cgr\.dev/chainguard/python@sha256:[0-9a-f]{64}", base
    ):
        raise ValueError("Unexpected base image identity")
    trivy_arch, trivy_sha, cosign_arch, cosign_sha = TOOLS[
        (platform.system(), platform.machine())
    ]
    with (
        tempfile.TemporaryDirectory(prefix="entrotter-image-audit-") as directory,
        client() as prefix,
    ):
        root = Path(directory)
        (root / "config.yaml").write_text("{}\n")
        (root / "ignore").write_text("")
        (root / "docker").mkdir()
        env = {"PATH": os.environ["PATH"], "DOCKER_CONFIG": str(root / "docker")}
        if "SSL_CERT_FILE" in os.environ:
            env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        verified_download(
            f"https://github.com/aquasecurity/trivy/releases/download/v{TRIVY_VERSION}/trivy_{TRIVY_VERSION}_{trivy_arch}.tar.gz",
            trivy_sha,
            root / "trivy.tar.gz",
            args.trivy_archive,
        )
        with tarfile.open(root / "trivy.tar.gz") as archive:
            entry = archive.getmember("trivy")
            if not entry.isfile() or entry.size > MAX_TOOL_BYTES:
                raise ValueError("Invalid scanner archive member")
            source = archive.extractfile(entry)
            if source is None:
                raise ValueError("Scanner binary missing")
            with source, (root / "trivy").open("wb") as target:
                shutil.copyfileobj(source, target)
        (root / "trivy").chmod(0o755)
        verified_download(
            f"https://github.com/sigstore/cosign/releases/download/v{COSIGN_VERSION}/cosign-{cosign_arch}",
            cosign_sha,
            root / "cosign",
            args.cosign_binary,
        )
        (root / "cosign").chmod(0o755)
        with (
            (output / "signature.json").open("wb") as signature,
            (output / "signature.log").open("wb") as log,
        ):
            subprocess.run(
                [
                    str(root / "cosign"),
                    "verify",
                    base,
                    "--certificate-identity",
                    IDENTITY,
                    "--certificate-oidc-issuer",
                    ISSUER,
                ],
                env=env,
                cwd=root,
                stdout=signature,
                stderr=log,
                check=True,
                timeout=120,
            )
        signatures = json.loads((output / "signature.json").read_text())
        if not signatures or any(
            s["critical"]["image"]["docker-manifest-digest"] != base.split("@")[1]
            for s in signatures
        ):
            raise ValueError("Base signature is not bound to the pinned digest")
        label = subprocess.check_output(
            [
                *prefix,
                "image",
                "inspect",
                "--format",
                '{{index .Config.Labels "org.entrotter.source"}}',
                image,
            ],
            text=True,
            timeout=10,
        ).strip()
        if label != source_digest:
            raise ValueError("Image source label does not match the checkout")
        command = [
            str(root / "trivy"),
            "image",
            "--config",
            str(root / "config.yaml"),
            "--cache-dir",
            str(cache),
            "--ignorefile",
            str(root / "ignore"),
            "--scanners",
            "vuln",
            "--pkg-types",
            "os,library",
            "--severity",
            "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
            "--ignore-unfixed=false",
            "--list-all-pkgs",
            "--image-src",
            "docker",
            "--docker-host",
            prefix[-1],
            "--timeout",
            "5m",
            "--no-progress",
            "--format",
            "json",
            "--output",
            str(output / "packages.json"),
            "--exit-code",
            "0",
            image,
        ]
        with (output / "scanner.log").open("wb") as log:
            subprocess.run(
                command,
                env=env,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=330,
            )
        database_path = cache / "db/metadata.json"
        database = json.loads(database_path.read_text())
        shutil.copyfile(database_path, output / "database.json")
        summary = evaluate(
            json.loads((output / "packages.json").read_text()), image, database
        )
        summary.update(
            {
                "source_digest": source_digest,
                "auditor_sha256": digest(Path(__file__)),
                "trivy_version": TRIVY_VERSION,
                "trivy_archive_sha256": trivy_sha,
                "cosign_version": COSIGN_VERSION,
                "cosign_binary_sha256": cosign_sha,
                "base_image": base,
                "verified_base_signer": IDENTITY,
                "verified_base_issuer": ISSUER,
                "database_sha256": digest(cache / "db/trivy.db"),
                "report_sha256": digest(output / "packages.json"),
            }
        )
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return 1 if summary["vulnerability_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify Anvil release provenance and scan its signed workspace Cargo inventory.

The signed upstream SBOM describes the whole Foundry checkout, not an exact
linked-binary dependency inventory. Non-Cargo components remain outside coverage.
"""

import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen

from check_image_security import (
    COSIGN_VERSION,
    ISSUER,
    TOOLS,
    TRIVY_VERSION,
    digest,
    verified_download,
)

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.8.3"
COMMIT = "cae51ad458f6abb64852b7709eb784352429825d"
IDENTITY = f"https://github.com/foundry-rs/foundry/.github/workflows/release.yml@refs/tags/v{VERSION}"
PROVENANCE = "https://slsa.dev/provenance/v1"
SPDX = "https://spdx.dev/Document/v2.3"
MAX_METADATA = 16 * 1024 * 1024
RELEASES = {
    "arm64": {
        "archive": "93fc23be26c8a902ca58fe54aa6ca28c880b58af95d052674933161df7928e6d",
        "sbom": "ea05ec78d5f0abb54c644ec9bd6ce6ed1200a87fc53b13912d480ebda1203771",
    },
    "amd64": {
        "archive": "7ca48e6ca3cac1bce1403ca67e5bc1dc3bc1fd818199c9957c7165079c228568",
        "sbom": "8fb1fd40f45ff7eb97f40a6f020586e1e486ba701ae891e6ee6f63fff9ea6c7b",
    },
}


def download_metadata(url, target, token=None):
    headers = {"User-Agent": "Entrotter-native-audit/0.1.0"}
    if token:
        # The only authenticated call is the fixed public GitHub API endpoint.
        if not url.startswith("https://api.github.com/repos/foundry-rs/foundry/"):
            raise ValueError("Refusing credentials outside the fixed upstream API")
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        data = response.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        raise ValueError("Release metadata exceeds size limit")
    target.write_bytes(data)
    return json.loads(data)


def statement(bundle):
    envelope = bundle["dsseEnvelope"]
    if envelope["payloadType"] != "application/vnd.in-toto+json":
        raise ValueError("Unexpected attestation payload type")
    payload = base64.b64decode(envelope["payload"], validate=True)
    if len(payload) > MAX_METADATA:
        raise ValueError("Attestation payload exceeds size limit")
    result = json.loads(payload)
    if result.get("_type") != "https://in-toto.io/Statement/v1":
        raise ValueError("Unexpected attestation statement schema")
    return result


def verify_claims(provenance, sbom_statement, sbom, manifest):
    """Additional checks after Cosign verifies both envelopes and certificates."""
    archive = RELEASES[manifest["architecture"]]["archive"]
    if (
        manifest["foundry_version"] != VERSION
        or manifest["foundry_archive_sha256"] != archive
    ):
        raise ValueError("Manifest is not the pinned Foundry release")
    if (
        provenance.get("predicateType") != PROVENANCE
        or sbom_statement.get("predicateType") != SPDX
    ):
        raise ValueError("Wrong attestation predicate type")
    archive_name = f"foundry_v{VERSION}_linux_{manifest['architecture']}.tar.gz"
    expected_archive = {"name": archive_name, "digest": {"sha256": archive}}
    if (
        expected_archive not in provenance["subject"]
        or expected_archive not in sbom_statement["subject"]
    ):
        raise ValueError("Attestations are not bound to the expected archive")
    if {
        "name": "anvil",
        "digest": {"sha256": manifest["anvil_binary_sha256"]},
    } not in provenance["subject"]:
        raise ValueError("Signed Anvil digest differs from the builder's binary")
    build = provenance["predicate"]["buildDefinition"]
    dependencies = build["resolvedDependencies"]
    if not any(
        d.get("digest", {}).get("gitCommit") == COMMIT
        and d.get("uri")
        == f"git+https://github.com/foundry-rs/foundry@refs/tags/v{VERSION}"
        for d in dependencies
    ):
        raise ValueError("Provenance does not bind the pinned source commit")
    if sbom_statement["predicate"] != sbom:
        raise ValueError("Downloaded SBOM differs from the signed predicate")
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise ValueError("Unexpected SBOM schema")
    if not any(
        p.get("name") == "anvil" and p.get("versionInfo") == VERSION
        for p in sbom["packages"]
    ):
        raise ValueError("Signed inventory does not include this Anvil release")


def evaluate(sbom, report, database, now=None):
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
        or report.get("ArtifactType") != "spdx"
    ):
        raise ValueError("Unexpected native inventory scan format/version")
    expected: Counter[tuple[str, str, str]] = Counter()
    outside = []
    for package in sbom["packages"]:
        purls = [
            r["referenceLocator"]
            for r in package.get("externalRefs", [])
            if r.get("referenceType") == "purl"
            and r["referenceLocator"].startswith("pkg:cargo/")
        ]
        if purls:
            if len(purls) != 1 or not package.get("versionInfo"):
                raise ValueError("Ambiguous Cargo package identity")
            expected[(package["name"], package["versionInfo"], purls[0])] += 1
        else:
            outside.append(
                {
                    "name": package["name"],
                    "version": package.get("versionInfo"),
                    "source": package.get("sourceInfo"),
                    "reason": "No Cargo package URL; outside this native Cargo advisory scan",
                }
            )
    if len(expected) < 1000 or not {"rustls", "revm", "tokio"}.issubset(
        {p[0] for p in expected}
    ):
        raise ValueError("Expected upstream Cargo inventory is missing")
    observed: Counter[tuple[str, str, str]] = Counter()
    findings = []
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Scanner returned no inventories")
    for result in results:
        if result.get("Class") != "lang-pkgs" or result.get("Type") != "cargo":
            raise ValueError("Unexpected inventory type in native Cargo scan")
        for package in result.get("Packages", []):
            observed[
                (package["Name"], package["Version"], package["Identifier"]["PURL"])
            ] += 1
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            raise ValueError("Invalid vulnerability inventory")
        for finding in vulnerabilities:
            if not finding.get("VulnerabilityID") or not finding.get("PkgName"):
                raise ValueError("Invalid finding identity")
        findings.extend(vulnerabilities)
    if observed != expected:
        raise ValueError(
            "Scanner did not cover every signed Cargo identity/version exactly"
        )
    return {
        "status": "findings" if findings else "passed",
        "signed_sbom_packages": len(sbom["packages"]),
        "cargo_packages": sum(expected.values()),
        "vulnerability_count": len(findings),
        "outside_cargo_inventory": outside,
        "database_updated_at": database["UpdatedAt"],
        "database_next_update": database["NextUpdate"],
        "policy": "Every detected Cargo advisory fails, including unfixed/low/unknown; no suppression or VEX",
        "limitations": [
            "Signed upstream SBOM scans the whole Foundry checkout; not the exact linked Anvil feature/target subset",
            "Workspace crates, GitHub Actions and all components without Cargo URLs are listed outside advisory coverage",
            "Compiler, native C libraries, build-system integrity, host/VM/daemon and undiscovered dependencies are not fully audited",
            "A valid provenance signature establishes upstream identity and claims, not independent review or reproducible compilation",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".quality/trivy-cache"))
    parser.add_argument("--trivy-archive", type=Path)
    parser.add_argument("--cosign-binary", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = args.cache.resolve()
    manifest = json.loads(args.manifest.read_text())
    pin = RELEASES[manifest["architecture"]]
    if (
        manifest["foundry_version"] != VERSION
        or manifest["foundry_archive_sha256"] != pin["archive"]
    ):
        raise ValueError("Unexpected Foundry build inputs")
    sbom = download_metadata(
        f"https://github.com/foundry-rs/foundry/releases/download/v{VERSION}/foundry_v{VERSION}_linux_{manifest['architecture']}.spdx.json",
        output / "signed-inventory.json",
    )
    if digest(output / "signed-inventory.json") != pin["sbom"]:
        raise ValueError("Upstream SBOM release digest mismatch")
    attestations = download_metadata(
        "https://api.github.com/repos/foundry-rs/foundry/attestations/sha256:"
        + pin["archive"],
        output / "attestations.json",
        os.environ.get("GH_TOKEN"),
    )
    selected = {}
    for attestation in attestations["attestations"]:
        bundle = attestation["bundle"]
        claim = statement(bundle)
        kind = claim.get("predicateType")
        if kind in (PROVENANCE, SPDX):
            if kind in selected:
                raise ValueError("Multiple upstream claims require deliberate review")
            selected[kind] = (bundle, claim)
    if set(selected) != {PROVENANCE, SPDX}:
        raise ValueError("Missing provenance or signed SBOM attestation")
    trivy_arch, trivy_sha, cosign_arch, cosign_sha = TOOLS[
        (platform.system(), platform.machine())
    ]
    with tempfile.TemporaryDirectory(prefix="entrotter-native-audit-") as directory:
        root = Path(directory)
        env = {"PATH": os.environ["PATH"]}
        if "SSL_CERT_FILE" in os.environ:
            env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        verified_download(
            f"https://github.com/sigstore/cosign/releases/download/v{COSIGN_VERSION}/cosign-{cosign_arch}",
            cosign_sha,
            root / "cosign",
            args.cosign_binary,
        )
        (root / "cosign").chmod(0o755)
        for kind, name in [(PROVENANCE, "provenance"), (SPDX, "sbom")]:
            bundle_path = output / f"{name}-bundle.json"
            bundle_path.write_text(json.dumps(selected[kind][0]) + "\n")
            with (output / f"{name}-verification.log").open("wb") as log:
                subprocess.run(
                    [
                        str(root / "cosign"),
                        "verify-blob-attestation",
                        "--bundle",
                        str(bundle_path),
                        "--certificate-identity",
                        IDENTITY,
                        "--certificate-oidc-issuer",
                        ISSUER,
                        "--certificate-github-workflow-sha",
                        COMMIT,
                        "--type",
                        kind,
                        "--digestAlg",
                        "sha256",
                        "--digest",
                        pin["archive"],
                    ],
                    env=env,
                    cwd=root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=120,
                )
        verify_claims(selected[PROVENANCE][1], selected[SPDX][1], sbom, manifest)
        verified_download(
            f"https://github.com/aquasecurity/trivy/releases/download/v{TRIVY_VERSION}/trivy_{TRIVY_VERSION}_{trivy_arch}.tar.gz",
            trivy_sha,
            root / "trivy.tar.gz",
            args.trivy_archive,
        )
        with tarfile.open(root / "trivy.tar.gz") as archive:
            member = archive.getmember("trivy")
            if not member.isfile() or member.size > 256 * 1024 * 1024:
                raise ValueError("Invalid scanner archive member")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("Scanner binary missing")
            with source, (root / "trivy").open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        (root / "trivy").chmod(0o755)
        (root / "config.yaml").write_text("{}\n")
        (root / "ignore").write_text("")
        with (output / "scanner.log").open("wb") as log:
            subprocess.run(
                [
                    str(root / "trivy"),
                    "sbom",
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
                    "--timeout",
                    "5m",
                    "--no-progress",
                    "--format",
                    "json",
                    "--output",
                    str(output / "packages.json"),
                    "--exit-code",
                    "0",
                    str(output / "signed-inventory.json"),
                ],
                env=env,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=330,
            )
    report = json.loads((output / "packages.json").read_text())
    if report.get("ArtifactName") != str(output / "signed-inventory.json"):
        raise ValueError("Scanner report is not bound to the signed SBOM input")
    database_path = cache / "db/metadata.json"
    database = json.loads(database_path.read_text())
    (output / "database.json").write_bytes(database_path.read_bytes())
    result = evaluate(sbom, report, database)
    result.update(
        {
            "foundry_version": VERSION,
            "foundry_source_commit": COMMIT,
            "architecture": manifest["architecture"],
            "archive_sha256": pin["archive"],
            "anvil_binary_sha256": manifest["anvil_binary_sha256"],
            "signed_sbom_sha256": pin["sbom"],
            "verified_signer": IDENTITY,
            "verified_issuer": ISSUER,
            "source_digest": manifest["source_digest"],
            "image_id": manifest["image_id"],
            "manifest_sha256": digest(args.manifest),
            "auditor_sha256": digest(Path(__file__)),
            "shared_tool_helper_sha256": digest(
                ROOT / "scripts/check_image_security.py"
            ),
            "trivy_version": TRIVY_VERSION,
            "trivy_archive_sha256": trivy_sha,
            "cosign_version": COSIGN_VERSION,
            "cosign_binary_sha256": cosign_sha,
            "database_sha256": digest(cache / "db/trivy.db"),
            "report_sha256": digest(output / "packages.json"),
        }
    )
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "outside_cargo_inventory"},
            indent=2,
        )
    )
    return 1 if result["vulnerability_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

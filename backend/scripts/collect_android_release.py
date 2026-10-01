"""Collect a qualified cloud APK, sign locally, and retain its exact provenance."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from android_release_artifact import (
    ARTIFACT_NAME,
    MANIFEST_NAME,
    git_value,
    read_json,
    require_artifact,
    require_inputs,
    require_qualified_run,
    require_same_payload,
    sha256,
    write_json,
)


def gh_json(endpoint: str) -> dict[str, Any]:
    result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def qualified_runs(repository: str, run_id: int, commit: str) -> dict[str, dict[str, Any]]:
    prefix = f"repos/{repository}/actions"
    build = gh_json(f"{prefix}/runs/{run_id}")
    require_qualified_run(build, repository, commit, "ci.yml")
    runs = {"ci.yml": build}
    for workflow in ("codeql.yml", "android-connected-test.yml"):
        listing = gh_json(f"{prefix}/workflows/{workflow}/runs?head_sha={commit}&event=push&per_page=1")
        if not listing["workflow_runs"]:
            raise ValueError(f"Missing independent main qualification: {workflow}")
        run = listing["workflow_runs"][0]
        require_qualified_run(run, repository, commit, workflow)
        runs[workflow] = run
    return runs


def download_inputs(repository: str, run: dict[str, Any], directory: Path) -> dict[str, Any]:
    listing = gh_json(f"repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100")
    candidates = [item for item in listing["artifacts"]
                  if item["name"].startswith(ARTIFACT_NAME + "-attempt-") and not item["expired"]]
    if not candidates:
        raise ValueError("The qualified CI run did not retain any release APK inputs")
    artifact = max(candidates, key=lambda item: item["id"])
    require_artifact(artifact, run)
    archive_path = directory / "cloud-inputs.zip"
    with archive_path.open("xb") as stream:
        subprocess.run(["gh", "api", f"repos/{repository}/actions/artifacts/{artifact['id']}/zip"],
                       check=True, stdout=stream)
    if f"sha256:{sha256(archive_path)}" != artifact["digest"]:
        raise ValueError("Downloaded archive does not match GitHub's artifact digest")
    expected = {MANIFEST_NAME, "app-gray-release-unsigned.apk", "app-internal-release-unsigned.apk"}
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise ValueError("Release archive contains unexpected or duplicate entries")
        for name in expected:
            with (directory / name).open("xb") as stream:
                stream.write(archive.read(name))
    return artifact


def signing_environment() -> dict[str, str]:
    names = ("TICKETBOX_KEYSTORE_PATH", "TICKETBOX_KEY_ALIAS",
             "TICKETBOX_KEYSTORE_PASSWORD", "TICKETBOX_KEY_PASSWORD")
    values = {name: os.environ.get(name, "") for name in names}
    if not all(values.values()) or not Path(values["TICKETBOX_KEYSTORE_PATH"]).is_file():
        raise ValueError("Configure the persistent release keystore and its four signing environment variables")
    return values


def sign_apk(arguments: argparse.Namespace, unsigned: Path, signed: Path) -> str:
    signing = signing_environment()
    jar = arguments.build_tools / "lib/apksigner.jar"
    signer = [str(arguments.java), "-jar", str(jar)]
    # Passwords stay in the inherited environment, never command arguments or receipts.
    aligner = arguments.build_tools / ("zipalign.exe" if os.name == "nt" else "zipalign")
    try:
        subprocess.run([str(aligner), "-c", "-P", "16", "4", str(unsigned)],
                       check=True, capture_output=True, text=True)
        subprocess.run([*signer, "sign", "--ks", signing["TICKETBOX_KEYSTORE_PATH"],
                        "--ks-key-alias", signing["TICKETBOX_KEY_ALIAS"],
                        "--ks-pass", "env:TICKETBOX_KEYSTORE_PASSWORD", "--key-pass", "env:TICKETBOX_KEY_PASSWORD",
                        "--out", str(signed), str(unsigned)], check=True, capture_output=True, text=True)
        verified = subprocess.run([*signer, "verify", "--verbose", "--print-certs", str(signed)],
                                  check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        raise ValueError("Android alignment/signature verification failed; no artifact was qualified") from None
    certificates = re.findall(r"Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", verified)
    if len(certificates) != 1 or certificates[0].lower() != arguments.certificate_sha256:
        raise ValueError("Signed APK does not have the approved release certificate")
    require_same_payload(unsigned, signed)
    return verified


def collect(arguments: argparse.Namespace) -> None:
    if git_value("status", "--porcelain", "--untracked-files=no") or git_value(
        "status", "--porcelain", "--untracked-files=all", "--", "android",
    ):
        raise ValueError("Use the clean, qualified main checkout")
    signing_environment()
    commit, tree = git_value("rev-parse", "HEAD"), git_value("rev-parse", "HEAD^{tree}")
    runs = qualified_runs(arguments.repository, arguments.run_id, commit)
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifact = download_inputs(arguments.repository, runs["ci.yml"], output)
    inputs = read_json(output / MANIFEST_NAME)
    attempt = int(artifact["name"].rsplit("-", 1)[1])
    require_inputs(inputs, output, arguments.repository, commit, tree, arguments.run_id, attempt)
    if inputs["server_url"] != arguments.server_url:
        raise ValueError("The compiled server URL does not match the intended release profile")
    package = inputs["packages"][arguments.flavor]
    unsigned, signed = output / package["file"], output / f"app-{arguments.flavor}-release.apk"
    verification = sign_apk(arguments, unsigned, signed)
    (output / "signature-verification.txt").write_text(verification, encoding="utf-8")
    receipt = {
        "schema": "ticketbox.signed-android-artifact/v1", "qualification": "artifact-only",
        "created_at_utc": datetime.now(UTC).isoformat(), "checkout_sha": commit, "tree_sha": tree,
        "flavor": arguments.flavor, "apk_file": signed.name, "apk_sha256": sha256(signed),
        "certificate_sha256": arguments.certificate_sha256, "unsigned_apk_sha256": package["sha256"],
        "apksigner_jar_sha256": sha256(arguments.build_tools / "lib/apksigner.jar"),
        "inputs_manifest_sha256": sha256(output / MANIFEST_NAME), "artifact": artifact,
        "qualification_runs": {name: {key: run[key] for key in ("id", "run_attempt", "head_sha", "html_url")}
                               for name, run in runs.items()},
    }
    write_json(output / "signed-artifact.json", receipt)
    print(f"Verified signed {arguments.flavor} artifact for {commit}: {signed}")
    print("Artifact provenance only. Exact-candidate installation and business rehearsal remain required; not RC ready.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="xxu29958-jpg/xpj")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--certificate-sha256", required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--flavor", choices=("gray", "internal"), default="gray")
    arguments = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{64}", arguments.certificate_sha256) is None:
        parser.error("--certificate-sha256 must be the lowercase SHA-256 of the approved release certificate")
    collect(arguments)


if __name__ == "__main__":
    main()

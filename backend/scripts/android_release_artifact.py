"""Bind the existing cloud release build to its downloadable APK bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_NAME = "ticketbox-android-release-inputs"
MANIFEST_NAME = "release-inputs.json"
SCHEMA = "ticketbox.android-release-inputs/v1"
_SIGNATURE_ENTRY = re.compile(r"META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))", re.IGNORECASE)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git_value(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments], check=True, capture_output=True, text=True,
    ).stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path.name}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_qualified_run(run: dict[str, Any], repository: str, commit: str, workflow: str) -> None:
    expected = {
        "head_sha": commit, "head_branch": "main", "event": "push",
        "status": "completed", "conclusion": "success", "path": f".github/workflows/{workflow}",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{workflow} has not qualified this exact main commit")
    if run.get("repository", {}).get("full_name") != repository:
        raise ValueError("Qualification belongs to a different repository")


def require_artifact(artifact: dict[str, Any], run: dict[str, Any]) -> None:
    origin = artifact.get("workflow_run", {})
    if re.fullmatch(rf"{ARTIFACT_NAME}-attempt-[1-9][0-9]*", artifact.get("name", "")) is None or artifact.get("expired") is not False:
        raise ValueError("The current release-input artifact is missing or expired")
    if origin.get("id") != run["id"] or origin.get("head_sha") != run["head_sha"]:
        raise ValueError("Artifact does not belong to the qualified build")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", "")) is None:
        raise ValueError("GitHub did not provide an artifact archive digest")


def require_inputs(manifest: dict[str, Any], directory: Path, repository: str, commit: str,
                   tree: str, run_id: int, run_attempt: int) -> None:
    expected = {"schema": SCHEMA, "repository": repository, "checkout_sha": commit,
                "source_sha": commit, "tree_sha": tree, "run_id": run_id, "run_attempt": run_attempt, "dirty": False}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Release inputs do not match the qualified clean main tree")
    packages = manifest.get("packages", {})
    if set(packages) != {"gray", "internal"}:
        raise ValueError("Both declared release flavors must be present")
    for flavor, package in packages.items():
        name = f"app-{flavor}-release-unsigned.apk"
        if package.get("file") != name or package.get("variant") != f"{flavor}Release":
            raise ValueError("Unexpected release variant or APK path")
        apk = directory / name
        if apk.stat().st_size != package["size_bytes"] or sha256(apk) != package["sha256"]:
            raise ValueError(f"Release APK bytes changed: {flavor}")


def _apk_payload(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("APK contains duplicate ZIP entries")
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in names
                if not _SIGNATURE_ENTRY.fullmatch(name) and not name.endswith("/")}


def require_same_payload(unsigned: Path, signed: Path) -> None:
    if _apk_payload(unsigned) != _apk_payload(signed):
        raise ValueError("Signing changed the APK application payload")


def _stage_flavor(flavor: str, output: Path) -> dict[str, Any]:
    directory = ROOT / f"android/app/build/outputs/apk/{flavor}/release"
    metadata = read_json(directory / "output-metadata.json")
    elements = metadata["elements"]
    if metadata["variantName"] != f"{flavor}Release" or len(elements) != 1:
        raise ValueError("Expected one universal APK for the declared release flavor")
    element = elements[0]
    name = f"app-{flavor}-release-unsigned.apk"
    if element["outputFile"] != name or element["filters"]:
        raise ValueError("Expected the unsigned universal release APK")
    target = output / name
    shutil.copyfile(directory / name, target)
    return {"file": name, "sha256": sha256(target), "size_bytes": target.stat().st_size,
            "application_id": metadata["applicationId"], "variant": metadata["variantName"],
            "version_name": element["versionName"], "version_code": element["versionCode"]}


def stage(arguments: argparse.Namespace) -> None:
    commit = git_value("rev-parse", "HEAD")
    parents = git_value("cat-file", "-p", "HEAD").partition("\n\n")[0].splitlines()
    if commit != arguments.checkout or (arguments.source != commit and f"parent {arguments.source}" not in parents):
        raise ValueError("Build does not match the previously verified qualification identity")
    if git_value("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked build inputs changed during the release build")
    output = arguments.output
    output.mkdir(parents=True, exist_ok=False)
    java = subprocess.run(["java", "-version"], check=True, capture_output=True, text=True)
    manifest = {
        "schema": SCHEMA, "repository": arguments.repository, "run_id": arguments.run_id,
        "run_attempt": arguments.run_attempt, "checkout_sha": commit, "source_sha": arguments.source,
        "tree_sha": git_value("rev-parse", "HEAD^{tree}"), "dirty": False,
        "server_url": arguments.server_url, "packages": {flavor: _stage_flavor(flavor, output)
                                                         for flavor in ("gray", "internal")},
        "toolchain": {
            "java": (java.stdout + java.stderr).strip(),
            "gradle_wrapper": (ROOT / "android/gradle/wrapper/gradle-wrapper.properties").read_text(),
            "version_catalog_sha256": sha256(ROOT / "android/gradle/libs.versions.toml"),
            "build_tools": (ROOT / "android/app/build/ticketbox-ci/build-tools-version.txt").read_text().strip(),
        },
    }
    write_json(output / MANIFEST_NAME, manifest)
    print(f"Staged unsigned release inputs for {commit}; this is not RC qualification.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--server-url", required=True)
    stage(parser.parse_args())


if __name__ == "__main__":
    main()

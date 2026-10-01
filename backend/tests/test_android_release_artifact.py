from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest

from scripts import android_release_artifact as release

COMMIT, TREE = "a" * 40, "b" * 40
REPOSITORY = "xxu29958-jpg/xpj"


def _run() -> dict:
    return {"id": 7, "head_sha": COMMIT, "head_branch": "main", "event": "push",
            "status": "completed", "conclusion": "success", "path": ".github/workflows/ci.yml",
            "repository": {"full_name": REPOSITORY}}


def _apk(path: Path, payload: bytes, *, signature: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("classes.dex", payload)
        archive.writestr("AndroidManifest.xml", b"synthetic manifest; not an installable test APK")
        if signature:
            archive.writestr("META-INF/CERT.SF", b"synthetic signing metadata")


def test_the_cloud_producer_and_collector_preserve_both_flavors_and_reject_changed_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "ROOT", tmp_path)
    output = tmp_path / "download"
    output.mkdir()
    packages = {}
    for flavor in ("gray", "internal"):
        build = tmp_path / f"android/app/build/outputs/apk/{flavor}/release"
        build.mkdir(parents=True)
        name = f"app-{flavor}-release-unsigned.apk"
        _apk(build / name, flavor.encode())
        metadata = {"variantName": f"{flavor}Release", "applicationId": f"example.{flavor}",
                    "elements": [{"outputFile": name, "filters": [], "versionName": "1.0", "versionCode": 1}]}
        (build / "output-metadata.json").write_text(json.dumps(metadata))
        packages[flavor] = release._stage_flavor(flavor, output)
    manifest = {"schema": release.SCHEMA, "repository": REPOSITORY, "checkout_sha": COMMIT,
                "source_sha": COMMIT, "tree_sha": TREE, "run_id": 7, "run_attempt": 1,
                "dirty": False, "packages": packages}
    release.require_inputs(manifest, output, REPOSITORY, COMMIT, TREE, 7, 1)
    wrong_source = copy.deepcopy(manifest)
    wrong_source["source_sha"] = "c" * 40
    with pytest.raises(ValueError, match="qualified clean main"):
        release.require_inputs(wrong_source, output, REPOSITORY, COMMIT, TREE, 7, 1)
    _apk(output / packages["gray"]["file"], b"different application")
    with pytest.raises(ValueError, match="APK bytes changed"):
        release.require_inputs(manifest, output, REPOSITORY, COMMIT, TREE, 7, 1)


@pytest.mark.parametrize("change", [{"event": "pull_request"}, {"conclusion": "failure"}, {"head_sha": "c" * 40}])
def test_pr_success_failed_gate_and_other_commit_cannot_qualify_a_release(change):
    run = _run()
    release.require_qualified_run(run, REPOSITORY, COMMIT, "ci.yml")
    run.update(change)
    with pytest.raises(ValueError, match="exact main"):
        release.require_qualified_run(run, REPOSITORY, COMMIT, "ci.yml")


def test_an_artifact_from_another_run_or_without_server_digest_is_rejected():
    artifact = {"name": release.ARTIFACT_NAME + "-attempt-1", "expired": False,
                "digest": "sha256:" + "d" * 64, "workflow_run": {"id": 7, "head_sha": COMMIT}}
    release.require_artifact(artifact, _run())
    other_run = copy.deepcopy(artifact)
    other_run["workflow_run"]["id"] = 8
    with pytest.raises(ValueError, match="qualified build"):
        release.require_artifact(other_run, _run())
    artifact.pop("digest")
    with pytest.raises(ValueError, match="archive digest"):
        release.require_artifact(artifact, _run())


def test_signing_metadata_is_allowed_but_replacing_code_or_adding_a_payload_is_not(tmp_path):
    unsigned, signed = tmp_path / "unsigned.apk", tmp_path / "signed.apk"
    _apk(unsigned, b"original application")
    _apk(signed, b"original application", signature=True)
    release.require_same_payload(unsigned, signed)
    _apk(signed, b"changed application", signature=True)
    with pytest.raises(ValueError, match="application payload"):
        release.require_same_payload(unsigned, signed)
    _apk(signed, b"original application", signature=True)
    with zipfile.ZipFile(signed, "a") as archive:
        archive.writestr("assets/extra-command", b"unexpected")
    with pytest.raises(ValueError, match="application payload"):
        release.require_same_payload(unsigned, signed)

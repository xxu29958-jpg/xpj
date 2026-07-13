"""Frozen Manager identity validates the complete installed payload."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend_manager import build_identity


def _file_evidence(root: Path, path: Path) -> dict[str, object]:
    value = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
    }


def _snapshot(files: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(files, key=lambda item: str(item["path"]).casefold())
    fingerprint_input = "".join(
        f'{item["path"]}\0{item["size"]}\0{item["sha256"]}\n' for item in ordered
    )
    return {
        "algorithm": "SHA-256",
        "fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        "files": ordered,
    }


def _frozen_payload(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    manager_dir = tmp_path / "manager"
    internal = manager_dir / "_internal"
    internal.mkdir(parents=True)
    executable = manager_dir / "ticketbox-manager.exe"
    executable.write_bytes(b"MZ-real-manager")
    runtime = internal / "python311.dll"
    runtime.write_bytes(b"runtime")
    payload = _snapshot([_file_evidence(manager_dir, executable), _file_evidence(manager_dir, runtime)])
    source = _snapshot(
        [
            {
                "path": "desktop/backend_manager/__main__.py",
                "size": 123,
                "sha256": hashlib.sha256(b"source-contract").hexdigest(),
            },
        ],
    )
    manifest = {
        "schema_version": 1,
        "artifact_type": "ticketbox-frozen-desktop-manager",
        "version": "1.2.0",
        "generated_at_utc": "2026-07-13T10:00:00.0000000Z",
        "toolchain": {"python": {"version": "3.11.15"}},
        "source": source,
        "payload": {**payload, "executable": _file_evidence(manager_dir, executable)},
    }
    manifest_path = manager_dir / "BUILD_PROVENANCE.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(build_identity.sys, "frozen", True, raising=False)
    monkeypatch.setattr(build_identity.sys, "executable", str(executable))
    return executable, manifest_path


def test_frozen_manager_identity_requires_complete_matching_payload(monkeypatch, tmp_path: Path) -> None:
    executable, _manifest = _frozen_payload(monkeypatch, tmp_path)

    identity = build_identity.load_frozen_manager_identity()

    assert identity == build_identity.FrozenManagerIdentity(executable.absolute(), "1.2.0")


def test_frozen_manager_identity_accepts_the_installer_numeric_version_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable, manifest_path = _frozen_payload(monkeypatch, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "1.2.0.7"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert build_identity.load_frozen_manager_identity() == build_identity.FrozenManagerIdentity(
        executable.absolute(),
        "1.2.0.7",
    )


@pytest.mark.parametrize(
    "version",
    ("1.2", "1.2.0-rc.1", "1.2.0+build.7", "1.2.65536"),
)
def test_frozen_manager_identity_rejects_versions_the_installer_cannot_publish(
    monkeypatch,
    tmp_path: Path,
    version: str,
) -> None:
    _executable, manifest_path = _frozen_payload(monkeypatch, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert build_identity.load_frozen_manager_identity() is None


@pytest.mark.parametrize("mutation", ["minimal", "missing", "tampered", "extra", "wrong_executable"])
def test_frozen_manager_identity_rejects_partial_or_changed_payload(
    monkeypatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    executable, manifest_path = _frozen_payload(monkeypatch, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "minimal":
        manifest = {
            "schema_version": 1,
            "artifact_type": "ticketbox-frozen-desktop-manager",
            "version": "1.2.0",
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "missing":
        (executable.parent / "_internal" / "python311.dll").unlink()
    elif mutation == "tampered":
        (executable.parent / "_internal" / "python311.dll").write_bytes(b"changed")
    elif mutation == "extra":
        (executable.parent / "leftover.dll").write_bytes(b"N-1")
    else:
        manifest["payload"]["executable"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert build_identity.load_frozen_manager_identity() is None


@pytest.mark.parametrize("unsafe_path", ["../escape.dll", "_internal\\escape.dll", "C:/escape.dll"])
def test_frozen_manager_identity_rejects_unsafe_manifest_paths(
    monkeypatch,
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    _executable, manifest_path = _frozen_payload(monkeypatch, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["payload"]["files"][0]["path"] = unsafe_path
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert build_identity.load_frozen_manager_identity() is None

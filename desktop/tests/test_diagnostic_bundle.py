"""Behavior tests for privacy-safe Desktop Manager diagnostic bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend_manager import diagnostic_bundle
from backend_manager.diagnostic_bundle import export_diagnostic_bundle


def _snapshot(files: dict[str, bytes]) -> dict:
    records = [
        {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for relative, content in sorted(files.items(), key=lambda item: item[0].casefold())
    ]
    fingerprint_input = "".join(
        f"{record['path']}\0{record['size']}\0{record['sha256']}\n" for record in records
    ).encode()
    return {
        "algorithm": "SHA-256",
        "fingerprint": hashlib.sha256(fingerprint_input).hexdigest(),
        "files": records,
    }


def _payload(root, files: dict[str, bytes]) -> dict:
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    snapshot = _snapshot(files)
    return {**snapshot, "executable": snapshot["files"][0]}


def _write_manifest(root, *, slot: str, version: str = "1.2.0"):
    root.mkdir(parents=True, exist_ok=True)
    executable = "ticketbox-manager.exe" if slot == "manager" else "ticketbox-backend.exe"
    manifest = root / "BUILD_PROVENANCE.json"
    document = {
        "schema_version": 1 if slot == "manager" else 3,
        "artifact_type": (
            "ticketbox-frozen-desktop-manager" if slot == "manager" else "ticketbox-frozen-backend"
        ),
        "generated_at_utc": "2026-07-13T00:00:00Z",
        "toolchain": {"private_build_path": r"C:\secret\toolchain"},
        "source": _snapshot({"source/main.py": b"print('safe')"}),
        "payload": _payload(root, {executable: b"MZ-safe"}),
    }
    document["version" if slot == "manager" else "backend_version"] = version
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return manifest, document


def _read_payload(bundle) -> tuple[bytes, dict]:
    with zipfile.ZipFile(bundle.path) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "README.txt"}
        raw = archive.read("diagnostics.json")
    return raw, json.loads(raw)


def test_bundle_contains_only_allowlisted_runtime_evidence_and_never_overwrites(tmp_path) -> None:
    status = {
        "runtime_mode": "installed",
        "running": True,
        "health": True,
        "health_state": "healthy",
        "runtime_access_state": "repair_required",
        "uptime_seconds": 42,
        "auto_restart": True,
        "restarts": 1,
        "backend_service_state": "running",
        "database_service_state": "running",
        "public_endpoint_state": "protected_unknown",
        "owner_state": "recovery_required",
        "owner_recovery_channel": "managed_host",
        "version": "1.2.0.7",
        "startup_failure_code": "installed_binding_invalid",
        "startup_failure_stage": "runtime_discovery",
        "control_error": None,
        "lan": "192.168.1.8:8000",
        "tunnel": "https://secret.example",
        "owner_url": "http://127.0.0.1:8000/owner",
        "log": [r"token=secret C:\ProgramData\Ticketbox\app\.env"],
    }
    now = datetime(2026, 7, 13, 6, 30, tzinfo=UTC)

    first = export_diagnostic_bundle(status, output_dir=tmp_path, now=now)
    first_bytes = first.path.read_bytes()
    second = export_diagnostic_bundle(status, output_dir=tmp_path, now=now)

    assert first.path != second.path
    assert first.path.read_bytes() == first_bytes
    assert re.fullmatch(
        r"Ticketbox-Diagnostics-20260713-063000-000000Z-[0-9a-f]{8}\.zip",
        first.file_name,
    )
    assert not list(tmp_path.glob("*.tmp"))
    raw, payload = _read_payload(first)
    assert payload["runtime"]["version"] == "1.2.0.7"
    assert payload["runtime"]["runtime_access_state"] == "repair_required"
    assert payload["runtime"]["owner_state"] == "recovery_required"
    assert payload["runtime"]["startup_failure_code"] == "installed_binding_invalid"
    assert payload["runtime"]["control_error_present"] is False
    assert payload["privacy"]["contains_tokens"] is False
    assert b"secret.example" not in raw
    assert b"ProgramData" not in raw
    assert b"192.168.1.8" not in raw


def test_bundle_publication_does_not_require_windows_hard_links_or_overwrite(
    tmp_path,
    monkeypatch,
) -> None:
    if os.name == "nt":
        monkeypatch.setattr(
            diagnostic_bundle.os,
            "link",
            lambda *_args: (_ for _ in ()).throw(AssertionError("hard links are not portable")),
        )
    bundle = export_diagnostic_bundle({}, output_dir=tmp_path)
    assert bundle.path.is_file()

    temporary = tmp_path / "publish.tmp"
    target = tmp_path / "existing.zip"
    temporary.write_bytes(b"new")
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        diagnostic_bundle._publish_without_replace(temporary, target)
    assert temporary.read_bytes() == b"new"
    assert target.read_bytes() == b"existing"


def test_bundle_validates_manager_and_backend_manifest_schemas(tmp_path, monkeypatch) -> None:
    manager, manager_document = _write_manifest(tmp_path / "manager", slot="manager", version="1.2.0.7")
    backend, backend_document = _write_manifest(tmp_path / "backend", slot="backend", version="1.2.0.7")
    monkeypatch.setattr(diagnostic_bundle, "_manifest_paths", lambda: (manager, backend))

    raw, payload = _read_payload(export_diagnostic_bundle({}, output_dir=tmp_path / "downloads"))

    assert payload["builds"] == [
        {
            "slot": "manager",
            "manifest_state": "valid",
            "artifact_type": "ticketbox-frozen-desktop-manager",
            "schema_version": 1,
            "version": "1.2.0.7",
            "generated_at_utc": "2026-07-13T00:00:00Z",
            "recorded_source_sha256": manager_document["source"]["fingerprint"],
            "installed_payload_integrity": "verified",
            "payload_sha256": manager_document["payload"]["fingerprint"],
            "executable_sha256": manager_document["payload"]["executable"]["sha256"],
        },
        {
            "slot": "backend",
            "manifest_state": "valid",
            "artifact_type": "ticketbox-frozen-backend",
            "schema_version": 3,
            "version": "1.2.0.7",
            "generated_at_utc": "2026-07-13T00:00:00Z",
            "recorded_source_sha256": backend_document["source"]["fingerprint"],
            "installed_payload_integrity": "verified",
            "payload_sha256": backend_document["payload"]["fingerprint"],
            "executable_sha256": backend_document["payload"]["executable"]["sha256"],
        },
    ]
    assert b"secret" not in raw
    assert b"private_build_path" not in raw


def test_bundle_reports_fixed_missing_and_invalid_manifest_slots(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "manager" / "BUILD_PROVENANCE.json"
    invalid = tmp_path / "backend" / "BUILD_PROVENANCE.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text('{"schema_version":999,"token":"do-not-export"}', encoding="utf-8")
    monkeypatch.setattr(diagnostic_bundle, "_manifest_paths", lambda: (missing, invalid))

    raw, payload = _read_payload(export_diagnostic_bundle({}, output_dir=tmp_path / "downloads"))

    assert payload["builds"] == [
        {"slot": "manager", "manifest_state": "missing", "installed_payload_integrity": "not_checked"},
        {"slot": "backend", "manifest_state": "invalid", "installed_payload_integrity": "not_checked"},
    ]
    assert b"do-not-export" not in raw


def test_manifest_summary_distinguishes_unreadable_and_oversized_evidence(tmp_path) -> None:
    class UnreadableManifest:
        def exists(self) -> bool:
            return True

        def is_file(self) -> bool:
            return True

        def stat(self):
            return SimpleNamespace(st_size=1)

        def read_text(self, *, encoding: str) -> str:
            raise PermissionError(encoding)

    manager_spec = diagnostic_bundle._MANIFEST_SPECS[0]
    assert diagnostic_bundle._manifest_summary(UnreadableManifest(), manager_spec) == {
        "slot": "manager",
        "manifest_state": "unreadable",
        "installed_payload_integrity": "not_checked",
    }

    oversized = tmp_path / "BUILD_PROVENANCE.json"
    oversized.write_bytes(b"x" * (diagnostic_bundle._MAX_MANIFEST_BYTES + 1))
    assert diagnostic_bundle._manifest_summary(oversized, manager_spec) == {
        "slot": "manager",
        "manifest_state": "invalid",
        "installed_payload_integrity": "not_checked",
    }


def test_bundle_reports_payload_mismatch_without_repeating_recorded_hashes(tmp_path, monkeypatch) -> None:
    manifest, document = _write_manifest(tmp_path / "manager", slot="manager")
    (manifest.parent / document["payload"]["executable"]["path"]).write_bytes(b"MZ-tampered")
    monkeypatch.setattr(diagnostic_bundle, "_manifest_paths", lambda: (manifest,))

    _, payload = _read_payload(export_diagnostic_bundle({}, output_dir=tmp_path / "downloads"))

    build = payload["builds"][0]
    assert build["manifest_state"] == "valid"
    assert build["installed_payload_integrity"] == "mismatch"
    assert "payload_sha256" not in build
    assert "executable_sha256" not in build


def test_frozen_manifest_discovery_keeps_both_expected_slots_when_files_are_missing(
    tmp_path,
    monkeypatch,
) -> None:
    executable = tmp_path / "Ticketbox" / "manager" / "ticketbox-manager.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.setattr(diagnostic_bundle.sys, "frozen", True, raising=False)
    monkeypatch.setattr(diagnostic_bundle.sys, "executable", str(executable))

    _, payload = _read_payload(export_diagnostic_bundle({}, output_dir=tmp_path / "downloads"))

    assert payload["builds"] == [
        {"slot": "manager", "manifest_state": "missing", "installed_payload_integrity": "not_checked"},
        {"slot": "backend", "manifest_state": "missing", "installed_payload_integrity": "not_checked"},
    ]

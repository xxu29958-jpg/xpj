from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest


def _record(root: Path, relative: str) -> dict[str, object]:
    payload = (root / Path(relative)).read_bytes()
    return {
        "path": relative.replace("\\", "/"),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _request(tmp_path: Path, *, release_id: str = "1.2.0") -> tuple[InstallRequest, Path]:
    app = tmp_path / "Ticketbox"
    release = app / "releases" / release_id
    backend = release / "backend" / "ticketbox-backend.exe"
    manager = release / "manager" / "ticketbox-manager.exe"
    postgres = app / "postgresql" / "bin" / "postgres.exe"
    lifecycle = app / "bin" / "lifecycle" / "TicketboxLifecycle.exe"
    for path, payload in (
        (backend, b"backend"),
        (manager, b"manager"),
        (postgres, b"postgres"),
        (lifecycle, b"lifecycle"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    files = [
        _record(app, f"releases/{release_id}/backend/ticketbox-backend.exe"),
        _record(app, f"releases/{release_id}/manager/ticketbox-manager.exe"),
        _record(app, "postgresql/bin/postgres.exe"),
        _record(app, "bin/lifecycle/TicketboxLifecycle.exe"),
    ]
    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20260821_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {"algorithm": "SHA-256", "files": files},
    }
    manifest_path = release / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="fresh-" + digest,
        request_hash="pending",
        target_release_id=release_id,
        app_dir=str(app),
        data_root=str(tmp_path / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=digest,
    )
    return request, manifest_path


def _verifier(request: InstallRequest) -> WindowsShipmentVerifier:
    return WindowsShipmentVerifier(Path(request.app_dir))


def test_verifier_binds_release_semantics_and_accepts_only_the_closed_file_set(
    tmp_path: Path,
) -> None:
    request, _manifest = _request(tmp_path)

    bound = _verifier(request).bind_and_verify(request)

    assert bound.release_manifest_sha256 == request.release_manifest_sha256
    assert bound.schema_revision == "20260821_0001"
    assert bound.schema_min_compatible == "1.2.0"
    assert bound.semantic_revision == "ticketbox-dataset-semantics-v1"


def test_release_product_version_must_be_semver_even_when_manifest_identity_matches(
    tmp_path: Path,
) -> None:
    request, _manifest = _request(tmp_path, release_id="release-1")

    with pytest.raises(LifecycleViolation, match="identity"):
        _verifier(request).bind_and_verify(request)


def test_shipment_product_version_reaches_alembic_and_backend_runtime_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request, _manifest = _request(tmp_path)
    bound = replace(
        _verifier(request).bind_and_verify(request),
        install_id="11111111-1111-4111-8111-111111111111",
        dataset_id="22222222-2222-4222-8222-222222222222",
    )
    helper = (
        Path(bound.app_dir)
        / "releases"
        / bound.target_release_id
        / "backend"
        / "ticketbox-database-maintenance.exe"
    )
    helper.write_bytes(b"MZ")

    class RecordingRunner:
        def __init__(self) -> None:
            self.argv: tuple[str, ...] = ()

        def run(self, argv, **_kwargs) -> CompletedCommand:
            self.argv = tuple(argv)
            return CompletedCommand(self.argv, 0, "", "")

    runner = RecordingRunner()
    WindowsAlembicAdapter(runner).apply(bound, "alembic")
    compatibility = runner.argv[runner.argv.index("--schema-min-compatible") + 1]

    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repo_root / "backend"))
    admission = importlib.import_module("app.database._database_generation_runtime_admission")
    admission._assert_exact_authority(
        {
            "session_user": "ticketbox_runtime",
            "current_user": "ticketbox_runtime",
            "current_database": "ticketbox",
            "runtime_role_ready": True,
            "runtime_role_isolated": True,
            "runtime_database_ready": True,
            "runtime_schema_ready": True,
            "runtime_tables_ready": True,
            "runtime_sequences_ready": True,
            "dataset_id": bound.dataset_id,
            "client_generation": bound.install_id,
            "restore_epoch": 0,
            "schema_revision": bound.schema_revision,
            "schema_min_compatible": compatibility,
            "semantic_revision": bound.semantic_revision,
            "restored_from_backup_id": None,
        },
        installation_id=bound.install_id,
        dataset_id=bound.dataset_id,
        target_revision=bound.schema_revision,
        revisions=(bound.schema_revision,),
    )


@pytest.mark.parametrize("mutation", ["missing", "changed", "extra"])
def test_verifier_rejects_missing_changed_or_extra_installed_bytes(
    tmp_path: Path,
    mutation: str,
) -> None:
    request, _manifest = _request(tmp_path)
    target = Path(request.app_dir) / "postgresql" / "bin" / "postgres.exe"
    if mutation == "missing":
        target.unlink()
    elif mutation == "changed":
        target.write_bytes(b"foreign")
    else:
        (Path(request.app_dir) / "unexpected.dll").write_bytes(b"foreign")

    with pytest.raises(LifecycleViolation, match="immutable shipment"):
        _verifier(request).bind_and_verify(request)


def test_verifier_rejects_a_manifest_not_bound_by_the_setup_request(tmp_path: Path) -> None:
    request, manifest = _request(tmp_path)
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(LifecycleViolation, match="manifest"):
        _verifier(request).bind_and_verify(replace(request))


def test_verifier_rejects_a_request_outside_the_bound_program_files_root(tmp_path: Path) -> None:
    request, _manifest = _request(tmp_path)
    expected = tmp_path / "Program Files" / "Ticketbox"

    with pytest.raises(LifecycleViolation, match="Program Files"):
        WindowsShipmentVerifier(expected).bind_and_verify(request)


@pytest.mark.skipif(os.name != "nt", reason="Windows known-folder contract")
def test_native_program_files_binding_is_absolute_and_product_scoped() -> None:
    root = ticketbox_install_root()

    assert root.is_absolute()
    assert root.name == "Ticketbox"

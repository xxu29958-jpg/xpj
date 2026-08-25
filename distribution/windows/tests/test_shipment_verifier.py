from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest


def _record(root: Path, relative: str) -> dict[str, object]:
    payload = (root / Path(relative)).read_bytes()
    return {
        "path": relative.replace("\\", "/"),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _request(tmp_path: Path) -> tuple[InstallRequest, Path]:
    app = tmp_path / "Ticketbox"
    release = app / "releases" / "1.2.0"
    backend = release / "backend" / "ticketbox-backend.exe"
    manager = release / "manager" / "ticketbox-manager.exe"
    postgres = app / "postgresql" / "bin" / "postgres.exe"
    lifecycle = app / "bin" / "TicketboxLifecycle.exe"
    for path, payload in (
        (backend, b"backend"),
        (manager, b"manager"),
        (postgres, b"postgres"),
        (lifecycle, b"lifecycle"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    files = [
        _record(app, "releases/1.2.0/backend/ticketbox-backend.exe"),
        _record(app, "releases/1.2.0/manager/ticketbox-manager.exe"),
        _record(app, "postgresql/bin/postgres.exe"),
        _record(app, "bin/TicketboxLifecycle.exe"),
    ]
    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.2.0",
        "product_version": "1.2.0",
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
        target_release_id="1.2.0",
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


def test_verifier_binds_release_semantics_and_accepts_only_the_closed_file_set(
    tmp_path: Path,
) -> None:
    request, _manifest = _request(tmp_path)

    bound = WindowsShipmentVerifier().bind_and_verify(request)

    assert bound.release_manifest_sha256 == request.release_manifest_sha256
    assert bound.schema_revision == "20260821_0001"
    assert bound.schema_min_compatible == "20260722_0001"
    assert bound.semantic_revision == "ticketbox-dataset-semantics-v1"


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
        WindowsShipmentVerifier().bind_and_verify(request)


def test_verifier_rejects_a_manifest_not_bound_by_the_setup_request(tmp_path: Path) -> None:
    request, manifest = _request(tmp_path)
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(LifecycleViolation, match="manifest"):
        WindowsShipmentVerifier().bind_and_verify(replace(request))

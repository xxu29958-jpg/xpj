"""Upgrade backup archive recovery-point and local PostgreSQL tree authority tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_existing_dataset_upgrade_backup_archive_validates_recovery_point_and_local_postgres_tree(
    tmp_path: Path,
) -> None:
    import hashlib
    import zipfile

    from app.database._existing_dataset_upgrade import (
        ExistingDatasetUpgradeError,
        _VerifiedBackupArchive,
    )

    install_id = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    source_rev = "20261029_0002"
    release_id = "1.2.1"

    app_dir = tmp_path / "app"
    pg_files = {
        "postgresql/bin/postgres.exe": b"pg17-postgres-bytes",
        "postgresql/bin/pg_controldata.exe": b"pg17-controldata-bytes",
    }
    for rel, content in pg_files.items():
        path = app_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def write_archive(
        dest: Path,
        *,
        recovery_point: dict | None = None,
        archive_pg_files: dict[str, bytes] | None = None,
    ) -> str:
        prog = {
            **(pg_files if archive_pg_files is None else archive_pg_files),
            f"releases/{release_id}/backend/ticketbox-backend.exe": b"backend-bytes",
        }
        manifest_payload = {
            "schema": "ticketbox-release-manifest-v1",
            "release_id": release_id,
            "product_version": release_id,
            "max_schema_revision": source_rev,
            "min_semantic_revision": "ticketbox-dataset-semantics-v1",
            "immutable_payload": {
                "algorithm": "SHA-256",
                "files": [
                    {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    for rel, data in sorted(prog.items())
                ],
            },
        }
        manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        members: dict[str, bytes] = {
            "data/pgdata/PG_VERSION": b"17\n",
            "data/pgdata/global/pg_control": b"pg-ctrl",
            "data/app/.env": b"TICKETBOX_ENV=1\n",
            "machine/installation.json": json.dumps({
                "schema": "ticketbox-installed-instance-v1",
                "install_id": install_id,
                "dataset_id": dataset_id,
                "expected_restore_epoch": 0,
                "active_release_id": release_id,
                "release_manifest_sha256": manifest_sha,
            }).encode("utf-8"),
            "machine/secrets/postgres.password": b"pw1",
            "machine/secrets/ticketbox_migrator.password": b"pw2",
            "machine/secrets/ticketbox_runtime.password": b"pw3",
            "machine/secrets/pgpass": b"pgpass",
            f"machine/operations/history/fresh-{manifest_sha}.json": json.dumps({
                "schema": "ticketbox-lifecycle-operation-v2",
                "operation_id": f"fresh-{manifest_sha}",
                "kind": "install",
                "phase": "committed",
                "install_id": install_id,
                "dataset_id": dataset_id,
                "target_release_id": release_id,
                "release_manifest_sha256": manifest_sha,
            }).encode("utf-8"),
            f"program/releases/{release_id}/release-manifest.json": manifest_bytes,
            **{f"program/{rel}": data for rel, data in prog.items()},
        }
        entries: dict[str, dict[str, object] | None] = {
            "program/": None,
            "machine/": None,
            "data/pgdata/": None,
            "data/attachments/": None,
            "data/app/": None,
        }
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
            for d in entries:
                zf.writestr(d, b"")
            for name, data in sorted(members.items()):
                zf.writestr(name, data)
                entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            cold_copy: dict[str, object] = {
                "schema": "ticketbox-beta-cold-copy-v2",
                "complete": True,
                "public_connectivity": {
                    "excluded_directory": "machine/connectors/cloudflare/secrets",
                    "credentials": "not_backed_up",
                    "after_restore": "configure_again",
                },
                "identity": {
                    "install_id": install_id,
                    "dataset_id": dataset_id,
                    "restore_epoch": 0,
                    "release_id": release_id,
                    "release_manifest_sha256": manifest_sha,
                    "schema_revision": source_rev,
                    "postgres_major": 17,
                },
                "entries": entries,
            }
            if recovery_point is not None:
                cold_copy["recovery_point"] = recovery_point
            zf.writestr("COLD_COPY.json", json.dumps(cold_copy).encode("utf-8"))
        return hashlib.sha256(dest.read_bytes()).hexdigest()

    # Valid archive with exact PG tree and valid recovery_point succeeds.
    good_rp = {
        "cutoff_utc": "2026-11-26T12:00:00Z",
        "api_version": "2026-10-11",
        "semantic_revision": "ticketbox-dataset-semantics-v1",
        "schema_revision": source_rev,
        "secret_disposition": {
            "db_bootstrap_material": "included_in_private_copy_for_rebind",
            "service_db_credentials": "rotated_on_restore",
            "connector_secrets": "excluded_reconfigure_on_target",
            "user_wincred_dpapi": "not_included_non_portable",
        },
        "matching_installer_requirement": {
            "release_id": release_id,
            "release_manifest_sha256": "a" * 64,
            "postgres_major": 17,
            "verify_command": "TicketboxLifecycle.exe verify-cold-copy --source backup.tbxcold",
        },
    }
    good = tmp_path / "good.tbxcold"
    good_sha = write_archive(good, recovery_point=good_rp)
    with _VerifiedBackupArchive(
        good,
        good_sha,
        dataset_id=dataset_id,
        installation_id=install_id,
        expected_restore_epoch=0,
        source_revision=source_rev,
        app_dir=app_dir,
    ):
        pass

    bad_rp = tmp_path / "bad-rp.tbxcold"
    bad_rp_sha = write_archive(bad_rp, recovery_point={"cutoff_utc": "bad"})
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="recovery_point"),
        _VerifiedBackupArchive(
            bad_rp,
            bad_rp_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass

    partial_pg = tmp_path / "partial-pg.tbxcold"
    partial_pg_sha = write_archive(
        partial_pg,
        recovery_point=good_rp,
        archive_pg_files={"postgresql/bin/postgres.exe": b"pg17-postgres-bytes"},
    )
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="PostgreSQL program tree"),
        _VerifiedBackupArchive(
            partial_pg,
            partial_pg_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass

    # Omitting app_dir must fail closed rather than skipping PG tree verification.
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="app_dir is required"),
        _VerifiedBackupArchive(
            good,
            good_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=None,
        ),
    ):
        pass

    # JSON boolean false for restore_epoch must not match expected integer 0.
    bool_epoch_archive = tmp_path / "bool-epoch.tbxcold"
    with zipfile.ZipFile(good, "r") as src, zipfile.ZipFile(bool_epoch_archive, "w", compression=zipfile.ZIP_STORED) as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "COLD_COPY.json":
                manifest = json.loads(data.decode("utf-8"))
                manifest["identity"]["restore_epoch"] = False
                data = json.dumps(manifest).encode("utf-8")
            dst.writestr(name, data)
    bool_epoch_sha = hashlib.sha256(bool_epoch_archive.read_bytes()).hexdigest()
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="identity does not match"),
        _VerifiedBackupArchive(
            bool_epoch_archive,
            bool_epoch_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass

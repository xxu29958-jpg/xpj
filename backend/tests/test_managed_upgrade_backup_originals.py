"""Real PostgreSQL tests for pre-upgrade cold-backup archives and retained originals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.database._existing_dataset_upgrade import (
    ExistingDatasetUpgradeError,
    run_existing_dataset_upgrade_action,
)
from tests._managed_upgrade_fixtures import (
    _DATASET_ID,
    _HEAD_REVISION,
    _INSTALL_ID,
    _PREV_REVISION,
    _read_attestation,
    _upgrade_topology,
    _write_valid_cold_copy_v2,
)
from tests.managed_postgres_test_support import _revision

pytestmark = pytest.mark.real_db


def test_missing_or_corrupt_retained_original_blocks_sql_upgrade_before_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.models.currency_binding import InstallationCurrencyBinding
    from app.services.identity_service import bootstrap_installation_owner
    from app.services.time_service import now_utc

    op_id = "upgrade-" + ("f" * 64)
    image_bytes = b"\xff\xd8\xff\xe0retained-original-receipt"
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    old_bytes = b"\xff\xd8\xff\xe0historical-replaced-receipt"
    old_sha = hashlib.sha256(old_bytes).hexdigest()
    bill_bytes = b"\xff\xd8\xff\xe0debt-bill-original"
    bill_sha = hashlib.sha256(bill_bytes).hexdigest()
    corrupt_bill = b"\xff\xd8\xff\xe0debt-bill-corrupted-pre-backup"
    rel_path = "uploads/owner/receipt.jpg"
    old_rel = "uploads/owner/old-receipt.jpg"
    bill_rel = "uploads/owner/bill.jpg"
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=0) as topology:
        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                with Session(bind=conn, expire_on_commit=False) as db:
                    bootstrap_installation_owner(
                        db,
                        operation_id="source-install",
                        installation_id=_INSTALL_ID,
                        bootstrap_secret="retained-original-test-bootstrap-secret-01",
                        commit=False,
                    )
                    binding = db.get(InstallationCurrencyBinding, 1)
                    assert binding is not None
                    activated_at = now_utc()
                    binding.state = "ACTIVE"
                    binding.home_currency_code = "CNY"
                    binding.minor_unit_exponent = 2
                    binding.rounding_mode = "ROUND_HALF_UP"
                    binding.binding_revision = 1
                    binding.provenance = "TEST_FIXTURE"
                    binding.evidence_sha256 = "0" * 64
                    binding.updated_at = activated_at
                    binding.activated_at = activated_at
                    db.flush()
                owner_account_id = int(conn.scalar(text("SELECT id FROM public.accounts LIMIT 1")) or 0)
                conn.execute(text("SELECT set_config('xpj.currency_writer', '1:1', true)"))
                expense_id = int(
                    conn.scalar(
                        text(
                            "INSERT INTO public.expenses ("
                            "public_id, tenant_id, merchant, category, source, amount_cents, original_amount_minor, "
                            "home_currency_code, original_currency_code, fx_status, status, duplicate_status, "
                            "items_sum_status, row_version, fact_revision, "
                            "image_path, image_hash, image_deleted_at, created_at, updated_at"
                            ") VALUES ("
                            "'exp-orig-1', 'owner', 'Coffee', 'Food', 'manual', 1200, 1200, "
                            "'CNY', 'CNY', 'ready', 'confirmed', 'none', 'no_items', 1, 0, "
                            ":image_path, :image_hash, NULL, NOW(), NOW()"
                            ") RETURNING id"
                        ),
                        {"image_path": rel_path, "image_hash": image_sha},
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'idem-hist-1', 'create_expense', :fp, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp": "1" * 64,
                        "body": json.dumps({
                            "id": str(expense_id),
                            "public_id": "exp-orig-1",
                            "image_path": old_rel,
                            "image_hash": old_sha,
                            "image_deleted_at": None,
                        }),
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'idem-hist-cleaned-1', 'create_expense', :fp1, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body1 AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        "), ("
                        "'owner', 'idem-hist-cleaned-2', 'clean_expense', :fp2, 'succeeded', "
                        "'expense', 'exp-orig-1', CAST(:body2 AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp1": "3" * 64,
                        "body1": json.dumps({
                            "id": expense_id,
                            "public_id": "exp-orig-1",
                            "image_path": "uploads/owner/cleaned-receipt.jpg",
                            "image_hash": "9" * 64,
                            "image_deleted_at": None,
                        }),
                        "fp2": "4" * 64,
                        "body2": json.dumps({
                            "id": str(expense_id),
                            "public_id": "exp-orig-1",
                            "image_path": "uploads/owner/cleaned-receipt.jpg",
                            "image_hash": "9" * 64,
                            "image_deleted_at": "2026-10-30T00:00:00Z",
                        }),
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO public.debt_bill_captures ("
                        "public_id, tenant_id, created_by_account_id, creation_key, capture_key, "
                        "request_fingerprint, accepted_receipt, file_name, media_type, input_sha256, "
                        "image_path, image_hash, image_size_bytes, status, row_version, created_at, updated_at"
                        ") VALUES ("
                        "'cap-orig-1', 'owner', :acct, 'ck-1', 'capk-1', :fp, CAST('{}' AS jsonb), "
                        "'bill.jpg', 'image/jpeg', :bill_sha, :bill_path, :bill_sha, :bill_len, "
                        "'pending', 1, NOW(), NOW()"
                        ")"
                    ),
                    {
                        "acct": owner_account_id,
                        "fp": "2" * 64,
                        "bill_sha": bill_sha,
                        "bill_path": bill_rel,
                        "bill_len": len(bill_bytes),
                    },
                )
        finally:
            admin_engine.dispose()

        data_root = (tmp_path / "data").resolve()
        uploads = data_root / "app" / "uploads" / "owner"
        uploads.mkdir(parents=True, exist_ok=True)
        upload_file = uploads / "receipt.jpg"
        old_file = uploads / "old-receipt.jpg"
        bill_file = uploads / "bill.jpg"
        archive_path = (tmp_path / "pre-upgrade.tbxcold").resolve()
        app_dir = (tmp_path / "app").resolve()

        def write_cold(
            entries: dict[str, object],
            members: dict[str, bytes] | None = None,
        ) -> str:
            index_only = {k: v for k, v in entries.items() if k not in (members or {})}
            return _write_valid_cold_copy_v2(
                archive_path,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                restore_epoch=0,
                source_revision=_PREV_REVISION,
                extra_members=members,
                extra_index_only=index_only,
                app_dir_for_pg=app_dir,
            )

        base_kwargs = {
            "database_url": topology.migrator_url.render_as_string(hide_password=False),
            "pgpassfile": topology.pgpass,
            "source_revision": _PREV_REVISION,
            "target_revision": _HEAD_REVISION,
            "dataset_id": _DATASET_ID,
            "installation_id": _INSTALL_ID,
            "expected_restore_epoch": 0,
            "operation_id": op_id,
            "data_root": data_root,
            "app_dir": app_dir,
            "program": topology.program,
            "contract": topology.contract,
            "seal_runtime_authority": False,
            "machine_secret": False,
        }

        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(**base_kwargs)
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        sha = write_cold({})
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        upload_file.write_bytes(image_bytes)
        old_file.write_bytes(old_bytes)
        bill_file.write_bytes(bill_bytes)

        index_only_entries = {
            "data/app/uploads/owner/receipt.jpg": {"size": len(image_bytes), "sha256": image_sha},
            "data/app/uploads/owner/old-receipt.jpg": {"size": len(old_bytes), "sha256": old_sha},
            "data/app/uploads/owner/bill.jpg": {"size": len(bill_bytes), "sha256": bill_sha},
        }
        sha_index_only = write_cold(index_only_entries)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_index_only
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        full_members = {
            "data/app/uploads/owner/receipt.jpg": image_bytes,
            "data/app/uploads/owner/old-receipt.jpg": old_bytes,
            "data/app/uploads/owner/bill.jpg": bill_bytes,
        }
        sha_full = write_cold(index_only_entries, full_members)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256="0" * 64
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        old_file.unlink()
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_full
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        old_file.write_bytes(old_bytes)

        corrupt_bill_sha = hashlib.sha256(corrupt_bill).hexdigest()
        bill_file.write_bytes(corrupt_bill)
        corrupt_entries = {
            **index_only_entries,
            "data/app/uploads/owner/bill.jpg": {"size": len(corrupt_bill), "sha256": corrupt_bill_sha},
        }
        corrupt_members = {**full_members, "data/app/uploads/owner/bill.jpg": corrupt_bill}
        sha_corrupt_bill = write_cold(corrupt_entries, corrupt_members)
        with pytest.raises(ExistingDatasetUpgradeError):
            run_existing_dataset_upgrade_action(
                **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_corrupt_bill
            )
        assert _revision(topology.admin_database_url) == _PREV_REVISION
        bill_file.write_bytes(bill_bytes)

        sha_valid = write_cold(index_only_entries, full_members)
        result = run_existing_dataset_upgrade_action(
            **base_kwargs, backup_archive=archive_path, backup_archive_sha256=sha_valid
        )
        assert result["result"] == "target_committed"
        assert result["backup_archive_sha256"] == sha_valid
        assert _revision(topology.admin_database_url) == _HEAD_REVISION
        attestation = _read_attestation(topology.admin_database_url)
        assert attestation is not None and attestation["backup_archive_sha256"] == sha_valid


def test_upgrade_cli_requires_backup_archive_and_sha256_arguments(tmp_path: Path) -> None:
    import importlib.util

    launch_path = Path(__file__).resolve().parents[1] / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_upgrade_cli_parse_probe", launch_path)
    assert spec is not None and spec.loader is not None
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)

    base = [
        "--upgrade-existing-dataset",
        "--database-url",
        "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5438/ticketbox",
        "--pgpassfile",
        str(tmp_path / "pgpass"),
        "--source-revision",
        _PREV_REVISION,
        "--target-revision",
        _HEAD_REVISION,
        "--dataset-id",
        _DATASET_ID,
        "--installation-id",
        _INSTALL_ID,
        "--expected-restore-epoch",
        "0",
        "--operation-id",
        "upgrade-" + ("a" * 64),
        "--data-root",
        str(tmp_path / "data"),
    ]
    with pytest.raises(SystemExit):
        launch._parse_existing_dataset_upgrade_args(base)
    with pytest.raises(SystemExit):
        launch._parse_existing_dataset_upgrade_args([*base, "--backup-archive", str(tmp_path / "pre.tbxcold")])
    parsed = launch._parse_existing_dataset_upgrade_args([
        *base,
        "--backup-archive",
        str(tmp_path / "pre.tbxcold"),
        "--backup-archive-sha256",
        "b" * 64,
    ])
    assert parsed.backup_archive == tmp_path / "pre.tbxcold"
    assert parsed.backup_archive_sha256 == "b" * 64


def test_pass4_backup_archive_parity_with_cold_restore_source_and_full_member_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle_root = str(Path(__file__).resolve().parents[2] / "distribution" / "windows" / "lifecycle")
    monkeypatch.syspath_prepend(lifecycle_root)
    from ticketbox_lifecycle.errors import LifecycleError
    from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
    from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

    op_id = "upgrade-" + ("7" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION, restore_epoch=1) as topology:
        data_root = (tmp_path / "data").resolve()
        (data_root / "app" / "uploads").mkdir(parents=True, exist_ok=True)
        app_dir = (tmp_path / "app").resolve()

        valid_archive = (tmp_path / "parity-valid.tbxcold").resolve()
        valid_sha = _write_valid_cold_copy_v2(
            valid_archive,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            app_dir_for_pg=app_dir,
        )
        restore_req = InstallRequest(
            schema=REQUEST_SCHEMA,
            command="restore",
            operation_id="restore-" + ("0" * 64),
            request_hash="pending",
            target_release_id="1.2.1",
            app_dir=str(app_dir),
            data_root=str(data_root),
            program_data_root=str(tmp_path / "programdata"),
            pg_service_name="TicketboxPg",
            backend_service_name="TicketboxBackend",
            pg_port=5432,
            backend_port=8000,
            postgres_major=17,
            release_manifest_sha256="0" * 64,
            schema_revision=_PREV_REVISION,
            semantic_revision="ticketbox-dataset-semantics-v1",
        )
        with valid_archive.open("rb") as stream:
            source = ColdRestoreSource(stream, valid_sha, restore_req)
            assert source.identity["dataset_id"] == _DATASET_ID

        no_inventory = (tmp_path / "no-inventory.tbxcold").resolve()
        no_inventory_sha = _write_valid_cold_copy_v2(
            no_inventory,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            include_program_inventory=False,
        )
        with pytest.raises(LifecycleError), no_inventory.open("rb") as stream:
            ColdRestoreSource(stream, no_inventory_sha, restore_req)
        with pytest.raises(ExistingDatasetUpgradeError) as no_inv_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=1,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=no_inventory,
                backup_archive_sha256=no_inventory_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "program inventory" in str(no_inv_exc.value.__cause__.__cause__)

        corrupt_member = (tmp_path / "corrupt-extra.tbxcold").resolve()
        corrupt_member_sha = _write_valid_cold_copy_v2(
            corrupt_member,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=1,
            source_revision=_PREV_REVISION,
            extra_members={"data/app/unrelated.bin": b"good-bytes"},
            corrupt_member_bytes={"data/app/unrelated.bin": b"tampered-bytes"},
        )
        with pytest.raises(LifecycleError), corrupt_member.open("rb") as stream:
            ColdRestoreSource(stream, corrupt_member_sha, restore_req)
        with pytest.raises(ExistingDatasetUpgradeError) as corrupt_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=1,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=corrupt_member,
                backup_archive_sha256=corrupt_member_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "checksum mismatch" in str(corrupt_exc.value.__cause__.__cause__)

        result = run_existing_dataset_upgrade_action(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            source_revision=_PREV_REVISION,
            target_revision=_HEAD_REVISION,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            expected_restore_epoch=1,
            operation_id=op_id,
            data_root=data_root,
            backup_archive=valid_archive,
            backup_archive_sha256=valid_sha,
            app_dir=app_dir,
            program=topology.program,
            contract=topology.contract,
            seal_runtime_authority=False,
            machine_secret=False,
        )
        assert result["result"] == "target_committed"


def test_pass4_historical_receipt_pg_integer_hex_and_overflow_match_source_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session

    from app.services.identity_service import bootstrap_installation_owner

    op_id = "upgrade-" + ("8" * 64)
    with _upgrade_topology(tmp_path, monkeypatch, initial_revision=_PREV_REVISION) as topology:
        data_root = (tmp_path / "data").resolve()
        (data_root / "app" / "uploads" / "owner").mkdir(parents=True, exist_ok=True)
        missing_rel = "uploads/owner/hex-missing.jpg"
        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'SET LOCAL ROLE "{topology.owner}"'))
                with Session(bind=conn, expire_on_commit=False) as db:
                    bootstrap_installation_owner(
                        db,
                        operation_id="source-install",
                        installation_id=_INSTALL_ID,
                        bootstrap_secret="hex-overflow-test-bootstrap-secret-01",
                        commit=False,
                    )
                    db.flush()
                conn.execute(
                    text(
                        "INSERT INTO public.api_idempotency_keys ("
                        "tenant_id, idempotency_key, operation, request_fingerprint, status, "
                        "resource_type, resource_id, response_body, created_at, completed_at, expires_at"
                        ") VALUES ("
                        "'owner', 'hex-id-key', 'create_expense', :fp, 'succeeded', "
                        "'expense', 'exp-hex-42', CAST(:body AS json), NOW(), NOW(), NOW() + INTERVAL '1 day'"
                        ")"
                    ),
                    {
                        "fp": "a" * 64,
                        "body": json.dumps({
                            "id": "0x2a",
                            "public_id": "exp-hex-42",
                            "image_path": missing_rel,
                            "image_hash": "a" * 64,
                            "image_deleted_at": None,
                        }),
                    },
                )
        finally:
            admin_engine.dispose()

        app_dir = (tmp_path / "app").resolve()
        archive_path = (tmp_path / "hex-check.tbxcold").resolve()
        archive_sha = _write_valid_cold_copy_v2(
            archive_path,
            dataset_id=_DATASET_ID,
            installation_id=_INSTALL_ID,
            restore_epoch=0,
            source_revision=_PREV_REVISION,
            app_dir_for_pg=app_dir,
        )
        with pytest.raises(ExistingDatasetUpgradeError) as hex_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=0,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "retained original" in str(hex_exc.value.__cause__.__cause__)
        assert _revision(topology.admin_database_url) == _PREV_REVISION

        admin_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
        try:
            with admin_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE public.api_idempotency_keys "
                        "SET response_body = CAST(:body AS json) "
                        "WHERE idempotency_key = 'hex-id-key'"
                    ),
                    {
                        "body": json.dumps({
                            "id": "2147483648",
                            "public_id": "exp-overflow",
                            "image_path": missing_rel,
                            "image_hash": "a" * 64,
                            "image_deleted_at": None,
                        })
                    },
                )
        finally:
            admin_engine.dispose()

        with pytest.raises(ExistingDatasetUpgradeError) as overflow_exc:
            run_existing_dataset_upgrade_action(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                source_revision=_PREV_REVISION,
                target_revision=_HEAD_REVISION,
                dataset_id=_DATASET_ID,
                installation_id=_INSTALL_ID,
                expected_restore_epoch=0,
                operation_id=op_id,
                data_root=data_root,
                backup_archive=archive_path,
                backup_archive_sha256=archive_sha,
                app_dir=app_dir,
                program=topology.program,
                contract=topology.contract,
                seal_runtime_authority=False,
                machine_secret=False,
            )
        assert "projection failed" in str(overflow_exc.value.__cause__.__cause__)
        assert _revision(topology.admin_database_url) == _PREV_REVISION

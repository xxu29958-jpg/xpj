"""Retained originals integrity checks for offline existing-dataset upgrade."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.database._existing_dataset_upgrade_archive import _VerifiedBackupArchive
from app.database._existing_dataset_upgrade_archive_rules import ExistingDatasetUpgradeError

_ORIGINAL_RECEIPT_OPERATIONS = frozenset({
    "attach_original",
    "verify_original",
    "replenish_original",
    "retry_original_cleanup",
    "cancel_original_cleanup",
})


def _verify_snapshot_original(
    *,
    relative_path: str,
    tenant_id: str,
    expected_sha256: str | None,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.errors import AppError
    from app.services.original_read_service import read_original_snapshot_in_root
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    try:
        with read_original_snapshot_in_root(
            relative_path=relative_path,
            tenant_id=tenant_id,
            expected_sha256=expected_sha256,
            upload_root=upload_root,
        ) as snapshot:
            resolved = resolve_upload_path_for_tenant_in_root(
                relative_path,
                tenant_id,
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("retained original is missing on disk")
            archive.verify_file(resolved, data_root=data_root, expected_sha256=snapshot.sha256)
    except AppError as exc:
        raise ExistingDatasetUpgradeError(
            f"retained original verification failed: {exc.error}"
        ) from exc


def _verify_expense_primary_originals(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    select_hash = "image_hash" if "image_hash" in columns else "NULL AS image_hash"
    where_deleted = " AND image_deleted_at IS NULL" if "image_deleted_at" in columns else ""
    rows = connection.execute(
        text(
            f"SELECT tenant_id, image_path, {select_hash} "
            f"FROM public.expenses WHERE image_path IS NOT NULL{where_deleted}"
        )
    ).all()
    for tenant_id, image_path, image_hash in rows:
        _verify_snapshot_original(
            relative_path=str(image_path),
            tenant_id=str(tenant_id),
            expected_sha256=None if image_hash is None else str(image_hash),
            data_root=data_root,
            upload_root=upload_root,
            archive=archive,
        )


def _verify_expense_thumbnails(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    if "thumbnail_path" not in columns:
        return
    where_thumb = " AND thumbnail_deleted_at IS NULL" if "thumbnail_deleted_at" in columns else ""
    rows = connection.execute(
        text(
            f"SELECT tenant_id, thumbnail_path FROM public.expenses "
            f"WHERE thumbnail_path IS NOT NULL{where_thumb}"
        )
    ).all()
    for tenant_id, thumb_path in rows:
        resolved = resolve_upload_path_for_tenant_in_root(
            str(thumb_path),
            str(tenant_id),
            upload_root=upload_root,
        )
        if resolved is None or not resolved.is_file():
            raise ExistingDatasetUpgradeError("retained thumbnail is missing on disk")
        archive.verify_file(resolved, data_root=data_root)


def _verify_expense_pending_cleanups(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.attachment_cleanup_contract import pending_cleanup_references
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    if "attachment_cleanup_request" not in columns:
        return
    rows = connection.execute(
        text(
            "SELECT tenant_id, attachment_cleanup_request FROM public.expenses "
            "WHERE attachment_cleanup_request IS NOT NULL"
        )
    ).all()
    for tenant_id, cleanup_req in rows:
        for reference in pending_cleanup_references(cleanup_req):
            resolved = resolve_upload_path_for_tenant_in_root(
                reference,
                str(tenant_id),
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("pending cleanup original reference is missing")
            archive.verify_file(resolved, data_root=data_root)


def _verify_expense_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    inspector = sa_inspect(connection)
    if not inspector.has_table("expenses", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("expenses", schema="public")}
    if "image_path" not in columns or "tenant_id" not in columns:
        return
    _verify_expense_primary_originals(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )
    _verify_expense_thumbnails(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )
    _verify_expense_pending_cleanups(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )


def _expenses_projection_cte(inspector) -> str:
    if not inspector.has_table("expenses", schema="public"):
        return (
            "SELECT CAST(NULL AS TEXT) AS tenant_id, CAST(NULL AS INTEGER) AS id, "
            "CAST(NULL AS TEXT) AS public_id, CAST(NULL AS TEXT) AS image_path, "
            "CAST(NULL AS TEXT) AS image_hash, CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at, "
            "CAST(NULL AS JSONB) AS attachment_cleanup_request WHERE FALSE"
        )
    columns = {col["name"] for col in inspector.get_columns("expenses", schema="public")}
    if not {"id", "tenant_id", "public_id", "image_path"}.issubset(columns):
        return (
            "SELECT CAST(NULL AS TEXT) AS tenant_id, CAST(NULL AS INTEGER) AS id, "
            "CAST(NULL AS TEXT) AS public_id, CAST(NULL AS TEXT) AS image_path, "
            "CAST(NULL AS TEXT) AS image_hash, CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at, "
            "CAST(NULL AS JSONB) AS attachment_cleanup_request WHERE FALSE"
        )
    hash_expr = "image_hash" if "image_hash" in columns else "CAST(NULL AS TEXT) AS image_hash"
    deleted_expr = (
        "image_deleted_at"
        if "image_deleted_at" in columns
        else "CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at"
    )
    cleanup_expr = (
        "attachment_cleanup_request"
        if "attachment_cleanup_request" in columns
        else "CAST(NULL AS JSONB) AS attachment_cleanup_request"
    )
    return (
        f"SELECT tenant_id, id, public_id, image_path, {hash_expr}, {deleted_expr}, {cleanup_expr} "
        "FROM public.expenses"
    )


def _verify_historical_receipt_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.services.original_reference_queries import historical_original_is_cleaned

    inspector = sa_inspect(connection)
    if not inspector.has_table("api_idempotency_keys", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("api_idempotency_keys", schema="public")}
    if not {"id", "tenant_id", "status", "resource_type", "response_body"}.issubset(columns):
        return
    expenses_cte = _expenses_projection_cte(inspector)
    query = text(
        "WITH accepted AS ("
        " SELECT r.id, r.tenant_id, r.resource_type,"
        "  CASE WHEN r.resource_type = 'expense_offset' THEN r.response_body -> 'root'"
        "       ELSE r.response_body END AS body"
        " FROM public.api_idempotency_keys AS r"
        " WHERE r.status = 'succeeded'"
        "   AND r.resource_type IN ('expense', 'expense_offset', 'upload_receipt')"
        "   AND r.response_body IS NOT NULL"
        "),"
        " classified AS ("
        " SELECT a.id AS accepted_id, a.tenant_id, a.resource_type, a.body,"
        "  (a.resource_type = 'expense'"
        "   AND (a.body ->> 'operation') = ANY(:ops)"
        "   AND (a.body ->> 'sha256') IS NOT NULL) AS original_command"
        " FROM accepted AS a"
        "),"
        " projected AS ("
        " SELECT c.accepted_id, c.tenant_id, c.resource_type, c.body, c.original_command,"
        "  CAST(CASE WHEN c.original_command THEN c.body ->> 'expense_id'"
        "            ELSE c.body ->> 'id' END AS INTEGER) AS expense_id,"
        "  (c.body ->> 'public_id') AS expense_public_id,"
        "  CASE WHEN c.original_command THEN c.body ->> 'sha256'"
        "       ELSE c.body ->> 'image_hash' END AS image_hash,"
        "  (c.body ->> 'image_deleted_at') AS image_deleted_at"
        " FROM classified AS c"
        "),"
        f" exp AS ({expenses_cte}),"
        " resolved AS ("
        " SELECT p.accepted_id, p.tenant_id, p.expense_id, p.expense_public_id,"
        "  CASE WHEN (p.resource_type = 'upload_receipt' OR p.original_command)"
        "        AND p.image_hash = e.image_hash THEN e.image_path"
        "       WHEN (p.resource_type = 'upload_receipt' OR p.original_command) THEN NULL"
        "       ELSE p.body ->> 'image_path' END AS image_path,"
        "  p.image_hash, p.image_deleted_at,"
        "  e.image_path AS current_image_path,"
        "  e.image_deleted_at AS current_image_deleted_at,"
        "  e.attachment_cleanup_request"
        " FROM projected AS p"
        " LEFT OUTER JOIN exp AS e"
        "   ON e.tenant_id = p.tenant_id"
        "  AND e.id = p.expense_id"
        "  AND e.public_id = p.expense_public_id"
        " WHERE p.expense_id IS NOT NULL"
        ")"
        " SELECT r.tenant_id, r.expense_id, r.expense_public_id, r.image_path, r.image_hash,"
        "  r.image_deleted_at,"
        "  MAX(CASE WHEN r.image_deleted_at IS NOT NULL THEN 1 ELSE 0 END) OVER ("
        "    PARTITION BY r.tenant_id, r.expense_id, r.expense_public_id, r.image_path"
        "  ) AS historical_image_cleaned,"
        "  r.current_image_path, r.current_image_deleted_at, r.attachment_cleanup_request"
        " FROM resolved AS r"
        " ORDER BY r.accepted_id"
    )
    try:
        rows = connection.execute(query, {"ops": sorted(_ORIGINAL_RECEIPT_OPERATIONS)}).mappings().all()
    except SQLAlchemyError as exc:
        raise ExistingDatasetUpgradeError("historical original receipt projection failed") from exc
    for row in rows:
        if historical_original_is_cleaned(row):
            continue
        image_path = row["image_path"]
        if not isinstance(image_path, str) or not image_path:
            continue
        image_hash = row["image_hash"]
        _verify_snapshot_original(
            relative_path=image_path,
            tenant_id=str(row["tenant_id"]),
            expected_sha256=image_hash if isinstance(image_hash, str) and image_hash else None,
            data_root=data_root,
            upload_root=upload_root,
            archive=archive,
        )


def _verify_debt_bill_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.attachment_cleanup_contract import pending_cleanup_references
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    inspector = sa_inspect(connection)
    if not inspector.has_table("debt_bill_captures", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("debt_bill_captures", schema="public")}
    if "image_path" not in columns or "tenant_id" not in columns:
        return
    deleted_expr = "image_deleted_at" if "image_deleted_at" in columns else "NULL AS image_deleted_at"
    cleanup_expr = (
        "attachment_cleanup_request"
        if "attachment_cleanup_request" in columns
        else "NULL AS attachment_cleanup_request"
    )
    hash_expr = "image_hash" if "image_hash" in columns else "NULL AS image_hash"
    rows = connection.execute(
        text(
            f"SELECT tenant_id, image_path, {deleted_expr}, {cleanup_expr}, {hash_expr} "
            "FROM public.debt_bill_captures"
        )
    ).all()
    for tenant_id, image_path, deleted_at, cleanup_req, image_hash in rows:
        if deleted_at is None and image_path:
            _verify_snapshot_original(
                relative_path=str(image_path),
                tenant_id=str(tenant_id),
                expected_sha256=None if image_hash is None else str(image_hash),
                data_root=data_root,
                upload_root=upload_root,
                archive=archive,
            )
        for reference in pending_cleanup_references(cleanup_req):
            resolved = resolve_upload_path_for_tenant_in_root(
                reference,
                str(tenant_id),
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("retained debt bill original is missing")
            archive.verify_file(resolved, data_root=data_root)


def _verify_upgrade_originals(
    connection: Connection,
    *,
    data_root: Path,
    backup_archive: Path,
    backup_archive_sha256: str,
    dataset_id: str,
    installation_id: str,
    expected_restore_epoch: int,
    source_revision: str,
    app_dir: Path | None = None,
) -> None:
    if not data_root.is_absolute() or not data_root.is_dir():
        raise ExistingDatasetUpgradeError("upgrade data_root is invalid or missing")
    upload_root = (data_root / "app" / "uploads").resolve()
    with _VerifiedBackupArchive(
        backup_archive,
        backup_archive_sha256,
        dataset_id=dataset_id,
        installation_id=installation_id,
        expected_restore_epoch=expected_restore_epoch,
        source_revision=source_revision,
        app_dir=app_dir,
    ) as archive:
        _verify_expense_originals(connection, data_root=data_root, upload_root=upload_root, archive=archive)
        _verify_historical_receipt_originals(
            connection, data_root=data_root, upload_root=upload_root, archive=archive
        )
        _verify_debt_bill_originals(connection, data_root=data_root, upload_root=upload_root, archive=archive)

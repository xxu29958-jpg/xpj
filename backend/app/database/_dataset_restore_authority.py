"""Database authority contract for one isolated dataset restore candidate."""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.errors import AppError
from app.services.dataset_backup_contract import DatasetBackupManifest
from app.services.dataset_restore_service import RestoredDatasetPlan

SANITATION_TABLES: tuple[str, ...] = (
    "desktop_activation_attempts",
    "session_refresh_attempts",
    "auth_tokens",
    "device_enrollment_attempts",
    "installation_owner_claims",
    "bootstrap_secret_consumptions",
    "upload_link_daily_usage",
    "upload_link_remote_attempts",
    "upload_links",
    "pairing_attempt_failures",
    "pairing_codes",
    "invitations",
    "installation_idempotency_keys",
    "scheduler_leases",
    "budget_advisor_quota_locks",
    "ai_transaction_temp_id_map",
)


def finalize_restored_dataset(
    connection: Connection,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    """Sanitize host credentials and publish Dataset Authority in one DB transaction."""

    alembic_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if alembic_revision != plan.schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1 FOR UPDATE"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) == _planned_authority_shape(plan):
        return
    if dict(observed) != _source_authority_shape(source):
        raise AppError("backup_incomplete", status_code=409)
    for table in SANITATION_TABLES:
        connection.execute(text(f'DELETE FROM "{table}"'))
    connection.execute(
        text(
            "DELETE FROM app_meta WHERE key IN "
            "('csrf_signing_key', 'database_generation_binding', 'budget_advisor_audit_key')"
        )
    )
    connection.execute(
        text(
            "UPDATE dataset_authority SET dataset_id = :dataset_id, "
            "client_generation = :client_generation, restore_epoch = :restore_epoch, "
            "schema_revision = :schema_revision, schema_min_compatible = :schema_min_compatible, "
            "semantic_revision = :semantic_revision, "
            "restored_from_backup_id = :backup_id WHERE singleton_id = 1"
        ),
        {
            "dataset_id": plan.dataset_id,
            "client_generation": plan.client_generation,
            "restore_epoch": plan.restore_epoch,
            "schema_revision": plan.schema_revision,
            "schema_min_compatible": plan.schema_min_compatible,
            "semantic_revision": plan.semantic_revision,
            "backup_id": plan.restored_from_backup_id,
        },
    )


def assert_restored_dataset_candidate_accepted(
    connection: Connection,
    *,
    plan: RestoredDatasetPlan,
) -> None:
    """Prove final Dataset Authority and absence of restored host capabilities."""

    if connection.scalar(text("SELECT version_num FROM alembic_version")) != plan.schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) != _planned_authority_shape(plan):
        raise AppError("backup_incomplete", status_code=409)
    for table in SANITATION_TABLES:
        if connection.scalar(text(f'SELECT count(*) FROM "{table}"')) != 0:
            raise AppError("backup_incomplete", status_code=409)
    if (
        connection.scalar(
            text(
                "SELECT count(*) FROM app_meta WHERE key IN "
                "('csrf_signing_key', 'database_generation_binding', 'budget_advisor_audit_key')"
            )
        )
        != 0
    ):
        raise AppError("backup_incomplete", status_code=409)


def _source_authority_shape(source: DatasetBackupManifest) -> dict[str, object]:
    authority = source.authority
    return {
        "dataset_id": authority.dataset_id,
        "client_generation": authority.client_generation,
        "restore_epoch": authority.restore_epoch,
        "schema_revision": authority.schema_revision,
        "schema_min_compatible": authority.schema_min_compatible,
        "semantic_revision": authority.semantic_revision,
        "restored_from_backup_id": authority.restored_from_backup_id,
    }


def _planned_authority_shape(plan: RestoredDatasetPlan) -> dict[str, object]:
    return {
        "dataset_id": plan.dataset_id,
        "client_generation": plan.client_generation,
        "restore_epoch": plan.restore_epoch,
        "schema_revision": plan.schema_revision,
        "schema_min_compatible": plan.schema_min_compatible,
        "semantic_revision": plan.semantic_revision,
        "restored_from_backup_id": plan.restored_from_backup_id,
    }


__all__ = [
    "SANITATION_TABLES",
    "assert_restored_dataset_candidate_accepted",
    "finalize_restored_dataset",
]

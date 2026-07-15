"""Single source of truth for PostgreSQL pytest lane classification."""

from __future__ import annotations

_STATEFUL_SERIAL_MODULE_PREFIXES = (
    "tests/test_alembic_",
    "tests/test_db_migration_",
    "tests/test_app_meta_service.py::",
    "tests/test_seed_identity_data.py::",
    "tests/test_ocr_facts_backfill_step3.py::",
    "tests/test_uploads_no_auto_move.py::",
)

_STATEFUL_SERIAL_NODE_SUBSTRINGS = (
    # These bootstrap recovery cases intentionally drop/rebuild the schema.
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_accepts_valid_secret",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_rolls_back_if_pairing_creation_fails",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_delayed_recovery_rejects_expired_pairing",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_recovery_finalizes_after_pairing_is_used",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_recovery_rejects_revoked_admin",
    "tests/test_auth_bootstrap_concurrency.py::test_two_sessions_bootstrap_recovery_avoids_device_token_deadlock",
    "tests/test_auth_bootstrap_concurrency.py::test_bootstrap_owner_rotates_credentials_after_listener_exposure",
    "tests/test_auth_bootstrap_concurrency.py::test_two_sessions_distinct_bootstrap_secrets_create_one_identity",
    "tests/test_auth_bootstrap_concurrency.py::test_exposed_bootstrap_principal_blocks_sensitive_identity_mutations",
    "tests/test_auth_bootstrap_concurrency.py::test_replacement_pairing_collision_is_reported_before_rotation",
)

_CLUSTER_SERIAL_MODULE_PREFIXES = (
    # Creates/drops PostgreSQL roles and must not overlap ordinary workers.
    "tests/test_db_migration_owner_preflight.py::",
)

_REAL_DB_NODE_SUBSTRINGS = (
    # Bootstrap recovery helpers use committed schema/engine operations.
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_accepts_valid_secret",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_rolls_back_if_pairing_creation_fails",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_delayed_recovery_rejects_expired_pairing",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_recovery_finalizes_after_pairing_is_used",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_recovery_rejects_revoked_admin",
    "tests/test_auth_bootstrap_concurrency.py::test_bootstrap_owner_rotates_credentials_after_listener_exposure",
    "tests/test_auth_bootstrap_concurrency.py::test_replacement_pairing_collision_is_reported_before_rotation",
    # Cross-session races and background work require independent connections.
    "::test_two_sessions",
    "tests/test_bill_split_hardening.py::test_create_invitation_row_locks_parent_expense",
    "tests/test_bill_split_debt_linkage.py::test_debt_failure_rolls_back_whole_accept",
    "tests/test_background_task_claim.py::",
    "tests/test_background_tasks.py::",
    "tests/test_expenses_reject.py::test_stale_reject_cannot_overwrite_confirmed_expense",
    "tests/test_expenses_ocr_routes.py::test_retry_ocr_rejects_stale_pending_snapshot",
    "tests/test_merchant_alias_optimistic_concurrency.py::test_delete_alias_with_stale_token_after_concurrent_patch",
    "tests/test_merchant_alias_optimistic_concurrency.py::test_delete_then_patch_race_resolves_to_404",
    # FastAPI background enrichment writes outside the shared savepoint.
    "tests/test_ocr_facts.py::test_upload_link_auto_ocr_writes_fact",
    "tests/test_ocr_facts.py::test_android_upload_auto_ocr_writes_fact",
    "tests/test_uploads.py::test_upload_accepts_decodable_heic_and_generates_jpeg_thumbnail",
    "tests/test_expenses_upload_confirm.py::test_confirm_delete_after_confirm_hides_image_and_thumbnail",
    # Legacy upload migration commits through its own engine connection.
    "tests/test_tenant_isolation.py::test_legacy_upload_paths_migrate_into_current_tenant_dir",
    "tests/test_tenant_isolation.py::test_legacy_upload_migration_leaves_database_only_reference_untouched",
    "tests/test_tenant_isolation.py::test_legacy_upload_migration_rename_failure_keeps_original_file_and_path",
    # These permission tests commit a role change through a second session.
    "tests/test_family_ledger_permissions.py::test_member_cannot_create_invitation",
    "tests/test_family_ledger_permissions.py::test_viewer_cannot_create_invitation",
    # These assertions require deterministic sequence values.
    "tests/test_learning_signal_hash.py::test_backfilled_row_via_signal_hash_suppresses_suggestion",
    "tests/test_learning_signal_hash.py::test_category_reject_via_signal_hash_suppresses_suggestion",
)


def postgres_test_markers(nodeid: str) -> tuple[str, ...]:
    """Return the committed-state markers required by one collected test."""

    normalized = nodeid.replace("\\", "/").partition("[")[0]
    stateful = any(
        normalized.startswith(prefix) for prefix in _STATEFUL_SERIAL_MODULE_PREFIXES
    ) or any(
        substring in normalized for substring in _STATEFUL_SERIAL_NODE_SUBSTRINGS
    )
    cluster = any(
        normalized.startswith(prefix) for prefix in _CLUSTER_SERIAL_MODULE_PREFIXES
    )
    real_db = stateful or cluster or any(
        substring in normalized for substring in _REAL_DB_NODE_SUBSTRINGS
    )

    markers: list[str] = []
    if real_db:
        markers.append("real_db")
    if stateful or cluster:
        markers.append("stateful_serial")
    if cluster:
        markers.append("cluster_serial")
    return tuple(markers)

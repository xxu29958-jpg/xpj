"""Release gate for cloud/multi-instance hardening contracts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _read(path: str) -> str:
    return (BACKEND_ROOT / path).read_text(encoding="utf-8")


def _read_repo(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _fail(message: str) -> None:
    print(f"FAIL: {message}")


def _require_tokens(label: str, text: str, tokens: tuple[str, ...]) -> list[str]:
    return [f"{label}: {token}" for token in tokens if token not in text]


def _advisor_quota_missing() -> list[str]:
    advisor_audit = _read("app/services/budget_advisor_service/_audit.py")
    missing = _require_tokens(
        "advisor quota",
        advisor_audit,
        (
            "def reserve_live_call_budget",
            "with_for_update",
            "IN_PROGRESS_ERROR_CODE",
            "complete_live_call_audit_row",
        ),
    )
    advisor_package = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (BACKEND_ROOT / "app/services/budget_advisor_service").glob("*.py")
    )
    if "_LIVE_CALL_LOCKS" in advisor_package:
        missing.append("advisor quota: process-local _LIVE_CALL_LOCKS returned")
    return missing


def _upload_link_missing() -> list[str]:
    upload_throttle = _read("app/services/upload_link_throttle_service.py")
    missing = _require_tokens(
        "upload link quota",
        upload_throttle,
        (
            "def reserve_upload_bytes",
            "def finalize_upload_bytes",
            "def release_upload_bytes",
            "with_for_update",
        ),
    )
    upload_migration = _read_repo("backend/migrations/versions/20260528_0001_upload_link_expiry.py")
    missing.extend(
        _require_tokens(
            "upload link expiry migration",
            upload_migration,
            (
                "UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS",
                "expires_at = datetime(",
                "ABS(id) % :spread_days",
            ),
        )
    )
    return missing


def _scheduler_missing() -> list[str]:
    scheduler_lease = _read("app/services/scheduler_lease_service.py")
    missing = _require_tokens(
        "scheduler lease",
        scheduler_lease,
        ("def try_claim_scheduler_lease", "scheduler_lease:", "rowcount"),
    )
    for path in (
        "app/services/fx_rate_scheduler.py",
        "app/services/learning_cleanup_scheduler.py",
        "app/services/budget_advisor_audit_cleanup_scheduler.py",
        "app/services/device_cleanup_scheduler.py",
    ):
        if "try_claim_scheduler_lease" not in _read(path):
            missing.append(f"scheduler lease: {path} is not lease-gated")
    return missing


def _auth_runtime_missing() -> list[str]:
    identity_model = _read("app/models/identity.py")
    identity_pair = _read("app/services/identity_service/_pair.py")
    session_lifecycle = _read("app/services/session_lifecycle_service.py")
    auth_runtime = identity_model + identity_pair + session_lifecycle + _read("app/config.py")
    missing = _require_tokens(
        "auth runtime",
        auth_runtime,
        (
            "uq_auth_tokens_active_principal",
            "grace_until",
            "invalid_pairing_code",
            "APP_TOKEN_ROTATION_GRACE_SECONDS",
        ),
    )
    if "used_pairing_code" in identity_pair or "expired_pairing_code" in identity_pair:
        missing.append("pairing: reject path leaks used/expired pairing states")
    return missing


def _app_meta_missing() -> list[str]:
    app_meta = _read("app/services/app_meta_service.py")
    database_init = _read("app/database/__init__.py")
    return _require_tokens(
        "fresh schema metadata",
        app_meta + database_init,
        (
            "def seed_fresh_schema_metadata",
            "BACKEND_VERSION",
            "_seed_fresh_schema_metadata_if_needed",
        ),
    )


def _advisor_provider_runtime_missing() -> list[str]:
    advisor_runtime = (
        _read("app/services/budget_advisor_service/_providers.py")
        + _read("app/services/budget_advisor_service/_runner.py")
        + _read("app/routes/budget_advisor.py")
        + _read("app/schemas/_budget_advisor.py")
    )
    return _require_tokens(
        "advisor provider runtime",
        advisor_runtime,
        (
            "def _validate_api_key_for_base_url",
            "def _api_key_has_unsafe_shape",
            "ord(ch) == 127",
            "len(api_key) < 8",
            "ai_advisor_provider_empty",
            "ai_advisor_provider_call_failed",
            "ai_advisor_response_parse_failed",
            "ai_advisor_no_advice",
            "reason_code",
        ),
    )


def _bill_split_missing() -> list[str]:
    bill_split_create = _read("app/services/bill_split_service/_create.py")
    return _require_tokens(
        "bill split cloud consistency",
        bill_split_create,
        (
            "with_for_update",
            "split_total_exceeds_parent",
            "split_invitation_already_pending",
            "split_amount_exceeds_parent",
            "split_receiver_invalid",
        ),
    )


def _thumbnail_cleanup_missing() -> list[str]:
    expense_create = _read("app/services/expense_service/_create.py")
    return _require_tokens(
        "thumbnail cleanup",
        expense_create,
        (
            "generated_thumbnail_path",
            "delete_relative_upload(generated_thumbnail_path)",
        ),
    )


def _ocr_csv_missing() -> list[str]:
    ocr_and_csv = (
        _read("app/models/ocr_facts.py")
        + _read("app/config.py")
        + _read("app/services/csv_import_batch_service/_apply.py")
    )
    return _require_tokens(
        "OCR/CSV scaling",
        ocr_and_csv,
        (
            "ck_ocr_facts_provider_valid",
            'LOCAL_LLM_MAX_CONCURRENT", "2"',
            "csv_import_apply_lease_minutes",
            "csv_import_row_apply_lease_minutes",
        ),
    )


def _duplicate_contract_missing() -> list[str]:
    duplicate_contract = (
        _read("app/services/file_service.py")
        + _read("app/services/duplicate_service.py")
        + _read("app/models/expense.py")
    )
    return _require_tokens(
        "duplicate detection",
        duplicate_contract,
        (
            "compute_image_perceptual_hash",
            "image_perceptual_hash",
            "ix_expenses_tenant_image_phash",
        ),
    )


def _regression_test_missing() -> list[str]:
    tests = "\n".join(path.read_text(encoding="utf-8") for path in (BACKEND_ROOT / "tests").glob("test_*.py"))
    return _require_tokens(
        "regression tests",
        tests,
        (
            "test_scheduler_lease_is_shared_across_sessions",
            "test_perceptual_hash_matches_tiny_visual_change",
            "test_refresh_rotates_token_and_graces_previous",
            "test_csv_import_row_claim_recovers_stale_apply_after_batch_lease_expires",
            # test_legacy_active_auth_tokens_deduplicate_before_unique_index was
            # retired with the SQLite startup migrator (PG-only, debt #4): it
            # exercised legacy-duplicate dedup during migration, which fresh PG
            # never has — the uq_auth_tokens_active_principal constraint stands alone.
            "test_fresh_schema_version_is_seeded_to_backend_version",
            "test_factory_rejects_public_api_key_with_unsafe_shape",
            "test_auto_enrich_cleans_generated_thumbnail_when_later_step_fails",
            "split_total_exceeds_parent",
            "ai_advisor_provider_empty",
        ),
    )


def main() -> int:
    missing: list[str] = []
    for collect_missing in (
        _advisor_quota_missing,
        _upload_link_missing,
        _scheduler_missing,
        _auth_runtime_missing,
        _app_meta_missing,
        _advisor_provider_runtime_missing,
        _bill_split_missing,
        _thumbnail_cleanup_missing,
        _ocr_csv_missing,
        _duplicate_contract_missing,
        _regression_test_missing,
    ):
        missing.extend(collect_missing())

    if missing:
        print("FAIL: cloud/multi-instance hardening contract drift:")
        for item in missing:
            print(f"  - {item}")
        return 1
    print("PASS: cloud/multi-instance hardening contract is enforced")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import json

from sqlalchemy import text

from app.database import engine
from app.services import backup_service
from app.services.migration_readiness_service import build_v1_migration_readiness_report


def _delete_backup(file_name: str | None) -> None:
    if not file_name:
        return
    backup_path = backup_service._backup_dir() / file_name  # noqa: SLF001
    try:
        backup_path.unlink()
    except FileNotFoundError:
        pass


def test_v1_migration_readiness_creates_pre_v1_backup(client) -> None:
    del client
    report = build_v1_migration_readiness_report(create_backup=True)

    try:
        payload = report.to_dict()
        assert payload["ready"] is True
        assert payload["target_version"] == "1.0"
        assert payload["database_kind"] == "sqlite"
        assert str(payload["backup_created"]).startswith("ticketbox-pre-v1.0-")
        assert payload["latest_backup"] == payload["backup_created"]
        assert payload["latest_backup_kind"] == "pre-v1.0"
        serialized = json.dumps(payload, ensure_ascii=False)
        assert ":\\" not in serialized
        assert "/data/" not in serialized
    finally:
        _delete_backup(report.backup_created)


def test_v1_migration_readiness_requires_latest_backup_to_be_pre_v1(client) -> None:
    del client
    manual_backup = backup_service.create_manual_backup()
    try:
        report = build_v1_migration_readiness_report(create_backup=False)

        assert report.ready is False
        assert report.latest_backup == manual_backup.file_name
        assert report.latest_backup_kind == "manual"
        checks = {check.code: check for check in report.checks}
        assert checks["backup_available"].status == "error"
        assert "pre-v1.0" in checks["backup_available"].message
    finally:
        _delete_backup(manual_backup.file_name)


def test_v1_migration_readiness_fails_when_v09_schema_is_missing(client) -> None:
    del client
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE dashboard_card_preferences"))

    report = build_v1_migration_readiness_report(create_backup=False)

    assert report.ready is False
    checks = {check.code: check for check in report.checks}
    assert checks["v09_tables"].status == "error"
    assert "dashboard_card_preferences" in checks["v09_tables"].message


def test_v1_migration_readiness_requires_family_permission_baseline_tables(client) -> None:
    del client
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ledger_audit_logs"))
        connection.execute(text("DROP TABLE invitations"))

    report = build_v1_migration_readiness_report(create_backup=False)

    assert report.ready is False
    checks = {check.code: check for check in report.checks}
    assert checks["v09_tables"].status == "error"
    assert "invitations" in checks["v09_tables"].message
    assert "ledger_audit_logs" in checks["v09_tables"].message


def test_v1_migration_readiness_requires_current_fx_and_item_tables(client) -> None:
    del client
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE exchange_rates"))
        connection.execute(text("DROP TABLE expense_items"))

    report = build_v1_migration_readiness_report(create_backup=False)

    assert report.ready is False
    checks = {check.code: check for check in report.checks}
    assert checks["v09_tables"].status == "error"
    assert "exchange_rates" in checks["v09_tables"].message
    assert "expense_items" in checks["v09_tables"].message

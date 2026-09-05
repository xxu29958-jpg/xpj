"""Real-PostgreSQL shape and transition probes for ADR-0061 C02."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.canonical_money_facts_contract import INSTALLATION_HOME_CURRENCY_KEY
from app.database import SessionLocal, engine
from app.errors import AppError
from app.models import (
    InstallationCurrencyAuditLog,
    InstallationIdempotencyKey,
)
from app.services.currency_adoption_service import (
    CurrencyAdoptionPreview,
    CurrencyAdoptionReceipt,
    adopt_currency_binding,
    adoption_preview,
)
from app.services.identity_service import authenticate_session_token, bootstrap_owner
from app.tenants import AuthContext
from tests._infra.c07_money_migration import (
    current_revision,
    reset_schema,
    run_alembic,
    seed_boundary_facts,
    seed_legacy_ocr_amount_fact,
    seed_owner,
)

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]

PREVIOUS_REVISION = "20260729_0001"
TARGET_REVISION = "20260802_0001"
HEAD_REVISION = "20260905_0001"
EVIDENCE_TABLES = (
    "bill_split_invitations",
    "budget_categories",
    "budgets",
    "category_rules",
    "csv_import_rows",
    "debt_adjustments",
    "debt_forgivenesses",
    "debts",
    "expense_items",
    "expense_splits",
    "expenses",
    "exchange_rates",
    "goals",
    "member_repayment_proposals",
    "monthly_income_plans",
    "recurring_items",
    "repayment_drafts",
    "repayments",
)


def _binding_row() -> dict[str, object]:
    with engine.connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM installation_currency_bindings WHERE singleton_id = 1"))
            .mappings()
            .one()
        )


def _budget_insert_sql() -> str:
    return """
        INSERT INTO budgets (
            public_id, tenant_id, month, total_amount_cents,
            non_monthly_amount_cents, rollover_amount_cents,
            excluded_categories, created_at, updated_at, row_version
        ) VALUES (
            :public_id, 'owner', '2026-08', 100,
            0, 0, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1
        )
    """


def _activate_cny_binding() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE installation_currency_bindings
                   SET state = 'ACTIVE',
                       home_currency_code = 'CNY',
                       minor_unit_exponent = 2,
                       rounding_mode = 'ROUND_HALF_UP',
                       binding_revision = 1,
                       provenance = 'FIRST_FACT_CLAIM',
                       evidence_sha256 = :digest,
                       updated_at = CURRENT_TIMESTAMP,
                       activated_at = CURRENT_TIMESTAMP
                 WHERE singleton_id = 1
                """
            ),
            {"digest": "0" * 64},
        )


def test_fresh_upgrade_has_complete_authority_shape() -> None:
    reset_schema()
    run_alembic(command.upgrade, "head")

    assert current_revision() == HEAD_REVISION
    binding = _binding_row()
    assert binding["state"] == "EMPTY"
    assert binding["currency_contract_version"] == 1
    assert binding["binding_revision"] == 0
    assert binding["home_currency_code"] is None

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert {
            "installation_currency_bindings",
            "installation_idempotency_keys",
            "installation_currency_audit_log",
        } <= set(inspector.get_table_names())
        assert {check["name"] for check in inspector.get_check_constraints("installation_currency_bindings")} == {
            "ck_installation_currency_binding_contract_version",
            "ck_installation_currency_binding_shape",
            "ck_installation_currency_binding_singleton",
            "ck_installation_currency_binding_state",
        }
        triggers = {
            (str(row.table_name), str(row.trigger_name))
            for row in connection.execute(
                text(
                    """
                    SELECT c.relname AS table_name, t.tgname AS trigger_name
                      FROM pg_trigger t
                      JOIN pg_class c ON c.oid = t.tgrelid
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = current_schema()
                       AND NOT t.tgisinternal
                    """
                )
            )
        }
    assert {(table, f"trg_currency_writer_{table}") for table in EVIDENCE_TABLES} <= triggers


def test_existing_money_fact_requires_explicit_adoption() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    seed_boundary_facts()

    run_alembic(command.upgrade, "head")

    binding = _binding_row()
    assert binding["state"] == "ADOPTION_REQUIRED"
    assert binding["binding_revision"] == 0
    assert binding["home_currency_code"] is None
    assert binding["evidence_sha256"] is None

    # A legacy planning fact has no per-row currency carrier. Before C02, the
    # verified bridge treated an unmarked legacy installation as CNY; adoption
    # must not offer a currency choice that would reinterpret the same integer.
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    seed_owner()
    with engine.begin() as connection:
        connection.execute(
            text(_budget_insert_sql()),
            {"public_id": str(uuid4())},
        )
    run_alembic(command.upgrade, "head")
    with SessionLocal() as db:
        preview = adoption_preview(db)
    assert preview.allowed_home_currency_codes == ("CNY",)

    # The released legacy rate table used a CNY-specific column name for a
    # source -> configured-home rate. A JPY installation could therefore hold
    # USD=150 (USD -> JPY); that row must not be reinterpreted as proof of CNY.
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    seed_owner()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app_meta (key, value, updated_at)
                VALUES (:key, 'JPY', CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at
                """
            ),
            {"key": INSTALLATION_HOME_CURRENCY_KEY},
        )
        connection.execute(
            text(
                """
                INSERT INTO exchange_rates (
                    public_id, tenant_id, currency_code, rate_date,
                    rate_to_cny, source, created_at, updated_at
                ) VALUES (
                    :public_id, 'owner', 'USD', DATE '2026-08-01',
                    150, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"public_id": str(uuid4())},
        )
    run_alembic(command.upgrade, "head")
    with SessionLocal() as db:
        preview = adoption_preview(db)
    assert preview.allowed_home_currency_codes == ("JPY",)

    # Without any explicit carrier the same rate only rules out USD as home;
    # owner adoption remains open to every other supported currency.
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM app_meta WHERE key = :key"),
            {"key": INSTALLATION_HOME_CURRENCY_KEY},
        )
    with SessionLocal() as db:
        preview = adoption_preview(db)
    assert "CNY" in preview.allowed_home_currency_codes
    assert "JPY" in preview.allowed_home_currency_codes
    assert "USD" not in preview.allowed_home_currency_codes


def test_writer_fence_requires_active_revision_proof() -> None:
    reset_schema()
    run_alembic(command.upgrade, "head")
    seed_owner()

    with (
        engine.begin() as connection,
        pytest.raises(
            DBAPIError,
            match="binding state EMPTY rejects writes",
        ),
    ):
        connection.execute(
            text(_budget_insert_sql()),
            {"public_id": str(uuid4())},
        )

    _activate_cny_binding()

    with (
        engine.begin() as connection,
        pytest.raises(
            DBAPIError,
            match="writer proof is missing or stale",
        ),
    ):
        connection.execute(
            text(_budget_insert_sql()),
            {"public_id": str(uuid4())},
        )

    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('xpj.currency_writer', '1:1', true)"))
        connection.execute(
            text(_budget_insert_sql()),
            {"public_id": str(uuid4())},
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM budgets")) == 1
        assert connection.scalar(text("SELECT current_setting('xpj.currency_writer', true)")) in (None, "")


def test_empty_authority_downgrade_round_trips_but_active_refuses() -> None:
    reset_schema()
    run_alembic(command.upgrade, TARGET_REVISION)
    run_alembic(command.downgrade, PREVIOUS_REVISION)
    assert current_revision() == PREVIOUS_REVISION
    with engine.connect() as connection:
        assert "installation_currency_bindings" not in inspect(connection).get_table_names()

    run_alembic(command.upgrade, TARGET_REVISION)
    assert _binding_row()["state"] == "EMPTY"
    _activate_cny_binding()

    with pytest.raises(
        RuntimeError,
        match="Refusing to remove an ACTIVE installation currency binding",
    ):
        run_alembic(command.downgrade, PREVIOUS_REVISION)
    assert current_revision() == TARGET_REVISION
    assert _binding_row()["state"] == "ACTIVE"


def _assert_adoption_rejections(
    db: Session,
    auth: AuthContext,
    preview: CurrencyAdoptionPreview,
) -> CurrencyAdoptionPreview:
    with pytest.raises(AppError) as conflicting_currency:
        adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=uuid4(),
            expected_contract_version=preview.currency_contract_version,
            home_code="JPY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="Incorrectly reinterpret explicit CNY facts as JPY.",
        )
    assert conflicting_currency.value.error == "currency_adoption_currency_conflict"
    with pytest.raises(AppError) as stale_contract:
        adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=uuid4(),
            expected_contract_version=preview.currency_contract_version + 1,
            home_code="CNY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="Owner verified that the imported installation used CNY minor units.",
        )
    assert stale_contract.value.error == "client_upgrade_required"
    changed = db.execute(
        text(
            "UPDATE ocr_facts SET parsed_amount_cents = "
            "COALESCE(parsed_amount_cents, 0) + 1 "
            "WHERE public_id = 'legacy-ocr-c07'"
        )
    )
    assert changed.rowcount == 1
    db.commit()
    changed_preview = adoption_preview(db)
    assert changed_preview.evidence_sha256 != preview.evidence_sha256
    with pytest.raises(AppError) as stale_evidence:
        adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=uuid4(),
            expected_contract_version=preview.currency_contract_version,
            home_code="CNY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="Owner verified that the imported installation used CNY minor units.",
        )
    assert stale_evidence.value.error == "currency_binding_evidence_changed"
    return changed_preview


def _assert_adoption_replay_contract(
    db: Session,
    auth: AuthContext,
    preview: CurrencyAdoptionPreview,
    key: UUID,
    receipt: CurrencyAdoptionReceipt,
) -> None:
    replay = adopt_currency_binding(
        db,
        auth=auth,
        idempotency_key=key,
        expected_contract_version=preview.currency_contract_version,
        home_code="CNY",
        expected_state="ADOPTION_REQUIRED",
        expected_revision=0,
        expected_evidence_sha256=preview.evidence_sha256,
        reason="Owner verified that the imported installation used CNY minor units.",
    )
    assert replay == receipt
    audit = db.query(InstallationCurrencyAuditLog).one()
    idem = db.get(InstallationIdempotencyKey, str(key))
    assert audit.action == "OWNER_ADOPTION"
    assert audit.actor_account_public_id is not None
    assert audit.actor_device_public_id is not None
    assert idem is not None
    assert idem.status == "succeeded"
    assert idem.receipt == receipt.__dict__
    with pytest.raises(AppError) as reused:
        adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=key,
            expected_contract_version=preview.currency_contract_version,
            home_code="CNY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="A different intent must not reuse the completed key.",
        )
    assert reused.value.error == "idempotency_key_reused"
    with pytest.raises(AppError) as already_active:
        adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=uuid4(),
            expected_contract_version=preview.currency_contract_version,
            home_code="CNY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="A new intent cannot adopt an active installation again.",
        )
    assert already_active.value.error == "currency_binding_already_active"


def test_owner_adoption_is_atomic_audited_and_replayable() -> None:
    reset_schema()
    run_alembic(command.upgrade, PREVIOUS_REVISION)
    with SessionLocal() as db:
        bootstrap = bootstrap_owner(
            db,
            account_name="Owner",
            ledger_name="Owner ledger",
            device_name="migration-admin",
        )
    admin_token = bootstrap.admin_token
    seed_boundary_facts()
    seed_legacy_ocr_amount_fact()
    run_alembic(command.upgrade, "head")

    with SessionLocal() as db:
        auth = authenticate_session_token(db, admin_token, {"app", "admin"})
        preview = adoption_preview(db)
        assert preview.allowed_home_currency_codes == ("CNY",)
        assert preview.evidence_health == "adoptable"
        preview = _assert_adoption_rejections(db, auth, preview)
        key = uuid4()
        receipt = adopt_currency_binding(
            db,
            auth=auth,
            idempotency_key=key,
            expected_contract_version=preview.currency_contract_version,
            home_code="CNY",
            expected_state="ADOPTION_REQUIRED",
            expected_revision=0,
            expected_evidence_sha256=preview.evidence_sha256,
            reason="Owner verified that the imported installation used CNY minor units.",
        )

    assert receipt.state == "ACTIVE"
    assert receipt.binding_revision == 1
    assert receipt.home_currency_code == "CNY"
    with SessionLocal() as db:
        auth = authenticate_session_token(db, admin_token, {"app", "admin"})
        _assert_adoption_replay_contract(db, auth, preview, key, receipt)

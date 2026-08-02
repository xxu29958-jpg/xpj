"""Add the installation currency authority and PostgreSQL writer fence.

Revision ID: 20260802_0001
Revises: 20260729_0001
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "20260802_0001"
down_revision = "20260729_0001"
branch_labels = None
depends_on = None

_BINDING_TABLE = "installation_currency_bindings"
_IDEMPOTENCY_TABLE = "installation_idempotency_keys"
_AUDIT_TABLE = "installation_currency_audit_log"
_WRITER_FUNCTION = "ticketbox_require_currency_writer"
_BINDING_GUARD_FUNCTION = "ticketbox_guard_currency_binding_transition"
_IMMUTABLE_FUNCTION = "ticketbox_reject_immutable_currency_audit_change"
_CATEGORY_RULE_TABLE = "category_rules"

_EVIDENCE_TABLES = (
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
    "ocr_facts",
    "recurring_items",
    "repayment_drafts",
    "repayments",
)
_WRITER_FENCE_TABLES = tuple(table for table in _EVIDENCE_TABLES if table != "ocr_facts")

_BINDING_SHAPE_CHECK = """
(
    state = 'ACTIVE'
    AND home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')
    AND (
        (home_currency_code IN ('JPY', 'KRW') AND minor_unit_exponent = 0)
        OR
        (home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'HKD') AND minor_unit_exponent = 2)
    )
    AND rounding_mode = 'ROUND_HALF_UP'
    AND binding_revision >= 1
    AND provenance IS NOT NULL
    AND evidence_sha256 ~ '^[0-9a-f]{64}$'
    AND activated_at IS NOT NULL
)
OR
(
    state IN ('EMPTY', 'ADOPTION_REQUIRED')
    AND home_currency_code IS NULL
    AND minor_unit_exponent IS NULL
    AND rounding_mode IS NULL
    AND binding_revision = 0
    AND provenance IS NULL
    AND evidence_sha256 IS NULL
    AND activated_at IS NULL
)
""".strip()


def _has_table(bind: sa.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _trigger_exists(bind: sa.Connection, table: str, trigger: str) -> bool:
    return bool(
        bind.scalar(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = :table
                      AND t.tgname = :trigger
                      AND NOT t.tgisinternal
                )
                """
            ),
            {"table": table, "trigger": trigger},
        )
    )


def _drop_trigger_if_present(bind: sa.Connection, table: str, trigger: str) -> None:
    if _has_table(bind, table) and _trigger_exists(bind, table, trigger):
        op.execute(sa.text(f'DROP TRIGGER "{trigger}" ON "{table}"'))


def _create_tables(bind: sa.Connection) -> None:
    if not _has_table(bind, _BINDING_TABLE):
        op.create_table(
            _BINDING_TABLE,
            sa.Column("singleton_id", sa.SmallInteger(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("home_currency_code", sa.String(length=3), nullable=True),
            sa.Column("minor_unit_exponent", sa.SmallInteger(), nullable=True),
            sa.Column("rounding_mode", sa.String(length=32), nullable=True),
            sa.Column("currency_contract_version", sa.Integer(), nullable=False),
            sa.Column("binding_revision", sa.Integer(), nullable=False),
            sa.Column("provenance", sa.String(length=64), nullable=True),
            sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "singleton_id = 1",
                name="ck_installation_currency_binding_singleton",
            ),
            sa.CheckConstraint(
                "state IN ('EMPTY', 'ADOPTION_REQUIRED', 'ACTIVE')",
                name="ck_installation_currency_binding_state",
            ),
            sa.CheckConstraint(
                "currency_contract_version >= 1",
                name="ck_installation_currency_binding_contract_version",
            ),
            sa.CheckConstraint(
                _BINDING_SHAPE_CHECK,
                name="ck_installation_currency_binding_shape",
            ),
            sa.PrimaryKeyConstraint("singleton_id"),
        )
    if not _has_table(bind, _IDEMPOTENCY_TABLE):
        op.create_table(
            _IDEMPOTENCY_TABLE,
            sa.Column("idempotency_key", sa.String(length=36), nullable=False),
            sa.Column("operation", sa.String(length=64), nullable=False),
            sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("receipt", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('in_progress', 'succeeded')",
                name="ck_installation_idempotency_status",
            ),
            sa.CheckConstraint(
                "idempotency_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
                name="ck_installation_idempotency_uuid4",
            ),
            sa.CheckConstraint(
                "(status = 'in_progress' AND receipt IS NULL AND completed_at IS NULL) "
                "OR (status = 'succeeded' AND receipt IS NOT NULL AND completed_at IS NOT NULL)",
                name="ck_installation_idempotency_completion_shape",
            ),
            sa.PrimaryKeyConstraint("idempotency_key"),
        )
        op.create_index(
            "ix_installation_idempotency_expires_at",
            _IDEMPOTENCY_TABLE,
            ["expires_at"],
            unique=False,
        )
    if not _has_table(bind, _AUDIT_TABLE):
        op.create_table(
            _AUDIT_TABLE,
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("actor_account_public_id", sa.String(length=36), nullable=True),
            sa.Column("actor_device_public_id", sa.String(length=36), nullable=True),
            sa.Column("before_snapshot", sa.JSON(), nullable=False),
            sa.Column("after_snapshot", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "action IN ('FIRST_FACT_CLAIM', 'OWNER_ADOPTION')",
                name="ck_installation_currency_audit_action",
            ),
            sa.CheckConstraint(
                "char_length(reason) BETWEEN 1 AND 500",
                name="ck_installation_currency_audit_reason",
            ),
            sa.CheckConstraint(
                "(actor_account_public_id IS NULL) = (actor_device_public_id IS NULL)",
                name="ck_installation_currency_audit_actor_shape",
            ),
            sa.PrimaryKeyConstraint("event_id"),
        )


def _lock_evidence_tables(bind: sa.Connection) -> None:
    missing = [table for table in _EVIDENCE_TABLES if not _has_table(bind, table)]
    if missing:
        raise RuntimeError("currency binding migration is missing evidence table(s): " + ", ".join(missing))
    op.execute(sa.text("SET LOCAL lock_timeout = '15s'"))
    for table in _EVIDENCE_TABLES:
        op.execute(sa.text(f'LOCK TABLE "{table}" IN SHARE ROW EXCLUSIVE MODE'))


def _has_adoption_evidence(bind: sa.Connection) -> bool:
    marker = bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM app_meta WHERE key = 'installation_home_currency')"))
    if marker:
        return True
    for table in _EVIDENCE_TABLES:
        predicate = (
            "amount_min_cents IS NOT NULL OR amount_max_cents IS NOT NULL" if table == _CATEGORY_RULE_TABLE else "TRUE"
        )
        if bind.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE {predicate})')):
            return True
    return False


def _seed_binding(bind: sa.Connection) -> None:
    exists = bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {_BINDING_TABLE} WHERE singleton_id = 1)"))
    if exists:
        return
    state = "ADOPTION_REQUIRED" if _has_adoption_evidence(bind) else "EMPTY"
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {_BINDING_TABLE} (
                singleton_id, state, currency_contract_version, binding_revision,
                created_at, updated_at
            ) VALUES (1, :state, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ),
        {"state": state},
    )


def _create_guard_functions() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {_WRITER_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                binding_state text;
                contract_version integer;
                revision integer;
                expected_proof text;
                actual_proof text;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: truncate is forbidden for %', TG_TABLE_NAME;
                END IF;
                SELECT state, currency_contract_version, binding_revision
                  INTO binding_state, contract_version, revision
                  FROM {_BINDING_TABLE}
                 WHERE singleton_id = 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: binding row is missing';
                END IF;
                IF binding_state <> 'ACTIVE' THEN
                    IF TG_TABLE_NAME = '{_CATEGORY_RULE_TABLE}'
                       AND binding_state = 'EMPTY'
                       AND TG_LEVEL = 'ROW' THEN
                        IF TG_OP = 'INSERT'
                           AND NEW.amount_min_cents IS NULL
                           AND NEW.amount_max_cents IS NULL THEN
                            RETURN NEW;
                        ELSIF TG_OP = 'UPDATE'
                           AND OLD.amount_min_cents IS NULL
                           AND OLD.amount_max_cents IS NULL
                           AND NEW.amount_min_cents IS NULL
                           AND NEW.amount_max_cents IS NULL THEN
                            RETURN NEW;
                        ELSIF TG_OP = 'DELETE'
                           AND OLD.amount_min_cents IS NULL
                           AND OLD.amount_max_cents IS NULL THEN
                            RETURN OLD;
                        END IF;
                    END IF;
                    RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: binding state % rejects writes', binding_state;
                END IF;
                expected_proof := contract_version::text || ':' || revision::text;
                actual_proof := current_setting('xpj.currency_writer', true);
                IF actual_proof IS DISTINCT FROM expected_proof THEN
                    RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: writer proof is missing or stale';
                END IF;
                IF TG_LEVEL = 'ROW' THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                END IF;
                RETURN NULL;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {_BINDING_GUARD_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                    RAISE EXCEPTION 'XPJ_CURRENCY_BINDING: binding deletion is forbidden';
                END IF;
                IF OLD.state IN ('EMPTY', 'ADOPTION_REQUIRED')
                   AND NEW.state = 'ACTIVE'
                   AND OLD.binding_revision = 0
                   AND NEW.binding_revision = 1
                   AND NEW.singleton_id = OLD.singleton_id
                   AND NEW.currency_contract_version = OLD.currency_contract_version
                   AND NEW.created_at = OLD.created_at THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'XPJ_CURRENCY_BINDING: invalid state transition %/% -> %/%',
                    OLD.state, OLD.binding_revision, NEW.state, NEW.binding_revision;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {_IMMUTABLE_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'XPJ_CURRENCY_AUDIT: audit rows are immutable';
            END;
            $$
            """
        )
    )


def _create_trigger(
    bind: sa.Connection,
    *,
    table: str,
    trigger: str,
    timing_and_events: str,
    each: str,
    function: str,
) -> None:
    if _trigger_exists(bind, table, trigger):
        return
    op.execute(
        sa.text(
            f'CREATE TRIGGER "{trigger}" {timing_and_events} ON "{table}" FOR EACH {each} EXECUTE FUNCTION {function}()'
        )
    )


def _create_triggers(bind: sa.Connection) -> None:
    for table in _WRITER_FENCE_TABLES:
        if table == _CATEGORY_RULE_TABLE:
            _create_trigger(
                bind,
                table=table,
                trigger=f"trg_currency_writer_{table}",
                timing_and_events="BEFORE INSERT OR UPDATE OR DELETE",
                each="ROW",
                function=_WRITER_FUNCTION,
            )
            _create_trigger(
                bind,
                table=table,
                trigger=f"trg_currency_writer_{table}_truncate",
                timing_and_events="BEFORE TRUNCATE",
                each="STATEMENT",
                function=_WRITER_FUNCTION,
            )
            continue
        _create_trigger(
            bind,
            table=table,
            trigger=f"trg_currency_writer_{table}",
            timing_and_events="BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE",
            each="STATEMENT",
            function=_WRITER_FUNCTION,
        )
    _create_trigger(
        bind,
        table=_BINDING_TABLE,
        trigger="trg_currency_binding_update_delete",
        timing_and_events="BEFORE UPDATE OR DELETE",
        each="ROW",
        function=_BINDING_GUARD_FUNCTION,
    )
    _create_trigger(
        bind,
        table=_BINDING_TABLE,
        trigger="trg_currency_binding_truncate",
        timing_and_events="BEFORE TRUNCATE",
        each="STATEMENT",
        function=_BINDING_GUARD_FUNCTION,
    )
    _create_trigger(
        bind,
        table=_AUDIT_TABLE,
        trigger="trg_currency_audit_update_delete",
        timing_and_events="BEFORE UPDATE OR DELETE",
        each="ROW",
        function=_IMMUTABLE_FUNCTION,
    )
    _create_trigger(
        bind,
        table=_AUDIT_TABLE,
        trigger="trg_currency_audit_truncate",
        timing_and_events="BEFORE TRUNCATE",
        each="STATEMENT",
        function=_IMMUTABLE_FUNCTION,
    )


def upgrade() -> None:
    bind = op.get_bind()
    _create_tables(bind)
    _lock_evidence_tables(bind)
    _seed_binding(bind)
    _create_guard_functions()
    _create_triggers(bind)


def assert_postcondition(bind: sa.Connection) -> None:
    """Prove the C02 authority and writer fence before migration commit."""

    inspector = sa.inspect(bind)
    required_tables = {
        _BINDING_TABLE,
        _IDEMPOTENCY_TABLE,
        _AUDIT_TABLE,
    }
    if not required_tables.issubset(inspector.get_table_names(schema="public")):
        raise RuntimeError("C02 postcondition is missing an authority table")

    binding_rows = bind.execute(
        sa.text(
            f"SELECT singleton_id, state, currency_contract_version, "
            f"binding_revision FROM public.{_BINDING_TABLE} ORDER BY singleton_id"
        )
    ).all()
    if (
        len(binding_rows) != 1
        or tuple(binding_rows[0])[:1] != (1,)
        or str(binding_rows[0].state) not in {"EMPTY", "ADOPTION_REQUIRED", "ACTIVE"}
        or int(binding_rows[0].currency_contract_version) != 1
        or int(binding_rows[0].binding_revision) not in {0, 1}
    ):
        raise RuntimeError("C02 postcondition has no valid binding singleton")

    binding_checks = {
        str(check["name"])
        for check in inspector.get_check_constraints(
            _BINDING_TABLE,
            schema="public",
        )
    }
    if binding_checks != {
        "ck_installation_currency_binding_contract_version",
        "ck_installation_currency_binding_shape",
        "ck_installation_currency_binding_singleton",
        "ck_installation_currency_binding_state",
    }:
        raise RuntimeError("C02 postcondition binding constraints drifted")

    expected_triggers = {
        (table, f"trg_currency_writer_{table}", _WRITER_FUNCTION)
        for table in _WRITER_FENCE_TABLES
    }
    expected_triggers.update(
        {
            (
                _CATEGORY_RULE_TABLE,
                f"trg_currency_writer_{_CATEGORY_RULE_TABLE}_truncate",
                _WRITER_FUNCTION,
            ),
            (
                _BINDING_TABLE,
                "trg_currency_binding_update_delete",
                _BINDING_GUARD_FUNCTION,
            ),
            (
                _BINDING_TABLE,
                "trg_currency_binding_truncate",
                _BINDING_GUARD_FUNCTION,
            ),
            (
                _AUDIT_TABLE,
                "trg_currency_audit_update_delete",
                _IMMUTABLE_FUNCTION,
            ),
            (
                _AUDIT_TABLE,
                "trg_currency_audit_truncate",
                _IMMUTABLE_FUNCTION,
            ),
        }
    )
    live_triggers = {
        (str(table), str(trigger), str(function))
        for table, trigger, function in bind.execute(
            sa.text(
                """
                SELECT c.relname, t.tgname, p.proname
                  FROM pg_trigger AS t
                  JOIN pg_class AS c ON c.oid = t.tgrelid
                  JOIN pg_namespace AS n ON n.oid = c.relnamespace
                  JOIN pg_proc AS p ON p.oid = t.tgfoid
                 WHERE n.nspname = 'public'
                   AND NOT t.tgisinternal
                   AND t.tgenabled = 'O'
                """
            )
        )
    }
    if not expected_triggers.issubset(live_triggers):
        raise RuntimeError("C02 postcondition writer fences are incomplete")

    functions = {
        str(name)
        for (name,) in bind.execute(
            sa.text(
                """
                SELECT p.proname
                  FROM pg_proc AS p
                  JOIN pg_namespace AS n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'public'
                   AND p.pronargs = 0
                   AND NOT p.prosecdef
                   AND p.proname = ANY(:names)
                """
            ),
            {
                "names": [
                    _WRITER_FUNCTION,
                    _BINDING_GUARD_FUNCTION,
                    _IMMUTABLE_FUNCTION,
                ]
            },
        )
    }
    if functions != {
        _WRITER_FUNCTION,
        _BINDING_GUARD_FUNCTION,
        _IMMUTABLE_FUNCTION,
    }:
        raise RuntimeError("C02 postcondition guard functions drifted")


def _drop_triggers(bind: sa.Connection) -> None:
    for table in reversed(_WRITER_FENCE_TABLES):
        _drop_trigger_if_present(bind, table, f"trg_currency_writer_{table}")
    _drop_trigger_if_present(
        bind,
        _CATEGORY_RULE_TABLE,
        f"trg_currency_writer_{_CATEGORY_RULE_TABLE}_truncate",
    )
    for trigger in (
        "trg_currency_binding_update_delete",
        "trg_currency_binding_truncate",
    ):
        _drop_trigger_if_present(bind, _BINDING_TABLE, trigger)
    for trigger in (
        "trg_currency_audit_update_delete",
        "trg_currency_audit_truncate",
    ):
        _drop_trigger_if_present(bind, _AUDIT_TABLE, trigger)


def _drop_functions() -> None:
    for function in (
        _WRITER_FUNCTION,
        _BINDING_GUARD_FUNCTION,
        _IMMUTABLE_FUNCTION,
    ):
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))


def _active_binding_exists(bind: sa.Connection) -> bool:
    if not _has_table(bind, _BINDING_TABLE):
        return False
    return bool(bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {_BINDING_TABLE} WHERE state = 'ACTIVE')")))


def _drop_tables(bind: sa.Connection, tables: Iterable[str]) -> None:
    for table in tables:
        if _has_table(bind, table):
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()
    if _active_binding_exists(bind):
        raise RuntimeError(
            "Refusing to remove an ACTIVE installation currency binding; restore a pre-C02 backup instead."
        )
    _drop_triggers(bind)
    _drop_functions()
    _drop_tables(bind, (_AUDIT_TABLE, _IDEMPOTENCY_TABLE, _BINDING_TABLE))

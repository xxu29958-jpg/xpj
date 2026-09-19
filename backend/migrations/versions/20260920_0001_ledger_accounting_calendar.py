"""Expand calendar evidence; policy adoption belongs to the configured runtime."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260920_0001"
down_revision = "20260919_0001"
branch_labels = None
depends_on = None

_TABLES = ("expenses", "expense_offset_facts")
_METADATA = (
    "calendar_revision", "user_local_date", "time_precision", "source_timezone",
    "source_utc_offset_seconds", "accounting_date_basis",
)


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"target": target, "expected": expected})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the accounting-calendar edge")


def _create_shape():
    op.add_column("bill_split_invitations", sa.Column("accounting_time_snapshot", JSONB(), nullable=True))
    op.create_table(
        "ledger_calendar_revisions",
        sa.Column("ledger_id", sa.String(64), sa.ForeignKey("ledgers.ledger_id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("timezone_name", sa.String(128), nullable=False),
        sa.Column("basis", sa.String(64), nullable=False),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_ledger_calendar_revision_positive"),
        sa.CheckConstraint("char_length(timezone_name) > 0", name="ck_ledger_calendar_timezone_present"),
        sa.CheckConstraint("char_length(basis) > 0", name="ck_ledger_calendar_basis_present"),
    )
    op.add_column("ledgers", sa.Column("calendar_revision", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_ledgers_calendar_revision", "ledgers", "ledger_calendar_revisions",
                          ["ledger_id", "calendar_revision"], ["ledger_id", "revision"])
    op.add_column("expenses", sa.Column("accounting_date", sa.Date(), nullable=True))
    for table in _TABLES:
        _create_fact_evidence(table)
    op.create_check_constraint("ck_expenses_date_only_instant", "expenses",
                               "time_precision IS DISTINCT FROM 'date_only' OR expense_time IS NULL")
    op.create_check_constraint("ck_expenses_accounting_date_scope", "expenses",
                               "accounting_date IS NULL OR calendar_revision IS NOT NULL")
    op.create_check_constraint("ck_expense_offset_facts_date_only_precision", "expense_offset_facts",
                               "time_precision IS NULL OR time_precision = 'date_only'")


def _create_fact_evidence(table):
    for name, kind in (
        ("calendar_revision", sa.Integer()), ("user_local_date", sa.Date()),
        ("time_precision", sa.String(16)), ("source_timezone", sa.String(128)),
        ("source_utc_offset_seconds", sa.Integer()), ("accounting_date_basis", sa.String(64)),
    ):
        op.add_column(table, sa.Column(name, kind, nullable=True))
    op.create_foreign_key(f"fk_{table}_calendar_revision", table, "ledger_calendar_revisions",
                          ["tenant_id", "calendar_revision"], ["ledger_id", "revision"])
    for suffix, expression in (
        ("calendar_positive", "calendar_revision IS NULL OR calendar_revision >= 1"),
        ("time_precision", "time_precision IS NULL OR time_precision IN ('instant', 'date_only', 'unknown')"),
        ("source_offset", "source_utc_offset_seconds IS NULL OR source_utc_offset_seconds BETWEEN -86399 AND 86399"),
        ("date_only_offset", "time_precision IS DISTINCT FROM 'date_only' OR source_utc_offset_seconds IS NULL"),
        ("time_evidence_scope", "calendar_revision IS NOT NULL OR (user_local_date IS NULL AND time_precision IS NULL "
         "AND source_timezone IS NULL AND source_utc_offset_seconds IS NULL AND accounting_date_basis IS NULL)"),
    ):
        op.create_check_constraint(f"ck_{table}_{suffix}", table, expression)


def _create_calendar_guards():
    op.execute("""
        CREATE FUNCTION ticketbox_calendar_adoption_rule() RETURNS ledger_calendar_revisions
        LANGUAGE plpgsql AS $$
        DECLARE proof jsonb; rule ledger_calendar_revisions;
        BEGIN
            proof := current_setting('xpj.calendar_adoption', true)::jsonb;
            IF proof->>'purpose' IS DISTINCT FROM 'legacy_adoption'
               OR proof->>'revision' IS DISTINCT FROM '1' THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: invalid adoption purpose';
            END IF;
            SELECT r.* INTO rule FROM ledger_calendar_revisions r JOIN ledgers l
                ON l.ledger_id = r.ledger_id AND l.calendar_revision = r.revision
                WHERE r.ledger_id = proof->>'ledger_id' AND r.revision = 1
                    AND r.basis = 'legacy_assumed';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: missing or stale ledger policy';
            END IF;
            RETURN rule;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION ticketbox_require_calendar_adoption_row() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE rule ledger_calendar_revisions; before_row jsonb; after_row jsonb;
            fields text[] := ARRAY['calendar_revision','user_local_date','time_precision',
                'source_timezone','source_utc_offset_seconds','accounting_date_basis'];
            expected_day date; expected_basis text;
        BEGIN
            IF COALESCE(current_setting('xpj.calendar_adoption', true), '') = '' THEN RETURN NEW; END IF;
            rule := ticketbox_calendar_adoption_rule();
            before_row := to_jsonb(OLD); after_row := to_jsonb(NEW);
            IF TG_TABLE_NAME = 'expenses' THEN fields := array_append(fields, 'accounting_date'); END IF;
            IF before_row - fields IS DISTINCT FROM after_row - fields THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: unrelated fact mutation';
            END IF;
            IF EXISTS (SELECT 1 FROM jsonb_each(before_row) e
                       WHERE e.key = ANY(fields) AND e.value <> 'null'::jsonb) THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: only first adoption is allowed';
            END IF;
            IF NEW.tenant_id IS DISTINCT FROM rule.ledger_id OR NEW.calendar_revision IS DISTINCT FROM rule.revision
               OR NEW.user_local_date IS NOT NULL OR NEW.source_timezone IS NOT NULL
               OR NEW.source_utc_offset_seconds IS NOT NULL THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: invented source evidence or wrong ledger';
            END IF;
            IF TG_TABLE_NAME = 'expenses' THEN
                expected_day := (COALESCE(OLD.expense_time, OLD.confirmed_at) AT TIME ZONE rule.timezone_name)::date;
                expected_basis := CASE WHEN OLD.expense_time IS NOT NULL THEN 'legacy_expense_time'
                    WHEN OLD.confirmed_at IS NOT NULL THEN 'legacy_confirmed_at' ELSE 'legacy_unknown' END;
                IF NEW.accounting_date IS DISTINCT FROM expected_day OR NEW.time_precision IS DISTINCT FROM 'unknown'
                   OR NEW.accounting_date_basis IS DISTINCT FROM expected_basis THEN
                    RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: incompatible legacy date';
                END IF;
            ELSIF NEW.time_precision IS DISTINCT FROM 'date_only'
                  OR NEW.accounting_date_basis IS DISTINCT FROM 'legacy_offset_date' THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: incompatible offset evidence';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER trg_calendar_adoption_{table} BEFORE UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION ticketbox_require_calendar_adoption_row()")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_reject_calendar_revision_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'ledger_calendar_revisions is append-only' USING ERRCODE = '55000';
        END $$
    """)
    op.execute("CREATE TRIGGER trg_ledger_calendar_revisions_append_only BEFORE UPDATE OR DELETE OR TRUNCATE "
               "ON ledger_calendar_revisions FOR EACH STATEMENT "
               "EXECUTE FUNCTION ticketbox_reject_calendar_revision_mutation()")


def _replace_currency_guard(*, calendar):
    # Frozen predecessor behavior. The dedicated mode never substitutes a currency
    # proof. Expenses retain their statement guard AND gain a mandatory row guard.
    calendar_branch = """
        IF COALESCE(current_setting('xpj.calendar_adoption', true), '') <> '' THEN
            IF TG_OP <> 'UPDATE' OR TG_TABLE_NAME NOT IN ('expenses', 'expense_offset_facts') THEN
                RAISE EXCEPTION 'XPJ_CALENDAR_FENCE: operation outside adoption';
            END IF;
            PERFORM ticketbox_calendar_adoption_rule();
            IF TG_LEVEL = 'ROW' THEN RETURN NEW; END IF;
            RETURN NULL;
        END IF;
    """ if calendar else ""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION ticketbox_require_currency_writer() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE binding_state text; contract_version integer; revision integer; expected_proof text; actual_proof text;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: truncate is forbidden for %', TG_TABLE_NAME;
            END IF;
            SELECT state, currency_contract_version, binding_revision INTO binding_state, contract_version, revision
                FROM installation_currency_bindings WHERE singleton_id = 1;
            IF NOT FOUND THEN RAISE EXCEPTION 'XPJ_CURRENCY_FENCE: binding row is missing'; END IF;
            {calendar_branch}
            IF binding_state <> 'ACTIVE' THEN
                IF TG_TABLE_NAME = 'category_rules' AND binding_state = 'EMPTY' AND TG_LEVEL = 'ROW' THEN
                    IF TG_OP = 'INSERT' AND NEW.amount_min_cents IS NULL AND NEW.amount_max_cents IS NULL THEN
                        RETURN NEW;
                    ELSIF TG_OP = 'UPDATE' AND OLD.amount_min_cents IS NULL AND OLD.amount_max_cents IS NULL
                        AND NEW.amount_min_cents IS NULL AND NEW.amount_max_cents IS NULL THEN RETURN NEW;
                    ELSIF TG_OP = 'DELETE' AND OLD.amount_min_cents IS NULL AND OLD.amount_max_cents IS NULL THEN
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
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END IF;
            RETURN NULL;
        END $$
    """)


def upgrade():
    _create_shape()
    _create_calendar_guards()
    _replace_currency_guard(calendar=True)
    _set_authority_revision(op.get_bind(), down_revision, revision)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ledger_calendar_revisions)")):
        raise RuntimeError("refusing to discard adopted calendar evidence")
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM bill_split_invitations WHERE accounting_time_snapshot IS NOT NULL)")):
        raise RuntimeError("refusing to discard frozen invitation time evidence")
    for table in _TABLES:
        columns = _METADATA + (("accounting_date",) if table == "expenses" else ())
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE "
                               + " OR ".join(f"{name} IS NOT NULL" for name in columns) + ")")):
            raise RuntimeError("refusing to discard stored time evidence")
    _replace_currency_guard(calendar=False)
    for table in _TABLES:
        op.execute(f"DROP TRIGGER trg_calendar_adoption_{table} ON {table}")
        op.drop_constraint(f"fk_{table}_calendar_revision", table, type_="foreignkey")
        for suffix in ("calendar_positive", "time_precision", "source_offset", "date_only_offset", "time_evidence_scope"):
            op.drop_constraint(f"ck_{table}_{suffix}", table, type_="check")
    op.drop_constraint("ck_expenses_date_only_instant", "expenses", type_="check")
    op.drop_constraint("ck_expenses_accounting_date_scope", "expenses", type_="check")
    op.drop_constraint("ck_expense_offset_facts_date_only_precision", "expense_offset_facts", type_="check")
    for table in _TABLES:
        for column in reversed(_METADATA):
            op.drop_column(table, column)
    op.drop_column("expenses", "accounting_date")
    op.drop_column("bill_split_invitations", "accounting_time_snapshot")
    op.drop_constraint("fk_ledgers_calendar_revision", "ledgers", type_="foreignkey")
    op.drop_column("ledgers", "calendar_revision")
    op.execute("DROP FUNCTION ticketbox_require_calendar_adoption_row()")
    op.execute("DROP FUNCTION ticketbox_calendar_adoption_rule()")
    op.drop_table("ledger_calendar_revisions")
    op.execute("DROP FUNCTION ticketbox_reject_calendar_revision_mutation()")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    if inspector.get_pk_constraint("ledger_calendar_revisions")["constrained_columns"] != ["ledger_id", "revision"]:
        raise RuntimeError("ledger calendar revision identity is missing")
    for table in _TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        if any(name not in columns or not columns[name]["nullable"] for name in _METADATA):
            raise RuntimeError("calendar evidence shape is missing")
        foreign_keys = {item["name"] for item in inspector.get_foreign_keys(table)}
        if f"fk_{table}_calendar_revision" not in foreign_keys:
            raise RuntimeError("calendar evidence ledger scope is missing")
    triggers = set(bind.scalars(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")))
    expected = {"trg_ledger_calendar_revisions_append_only", *(f"trg_calendar_adoption_{table}" for table in _TABLES)}
    if expected - triggers:
        raise RuntimeError("calendar evidence guards are missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected_revision = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected_revision:
        raise RuntimeError("dataset authority is not aligned with the accounting calendar")

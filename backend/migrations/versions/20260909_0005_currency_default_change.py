"""Allow an explicit next default revision without reinterpreting recorded money."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0005"
down_revision = "20260909_0004"
branch_labels = None
depends_on = None

_ACTION_CHECK = "ck_installation_currency_audit_action"
_GUARD = "ticketbox_guard_currency_binding_transition"
_DEFAULT_CHANGE = """
    IF OLD.state = 'ACTIVE' AND NEW.state = 'ACTIVE'
       AND NEW.binding_revision = OLD.binding_revision + 1
       AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code
       AND NEW.provenance = 'OWNER_DEFAULT_CHANGE'
       AND NEW.singleton_id = OLD.singleton_id
       AND NEW.currency_contract_version = OLD.currency_contract_version
       AND NEW.created_at = OLD.created_at
       AND NEW.activated_at = OLD.activated_at
       AND NEW.rounding_mode = OLD.rounding_mode
       AND NEW.evidence_sha256 = OLD.evidence_sha256 THEN
        RETURN NEW;
    END IF;
"""


def _install_guard(*, allow_default_change: bool) -> None:
    op.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_GUARD}()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'XPJ_CURRENCY_BINDING: binding deletion is forbidden';
            END IF;
            IF OLD.state IN ('EMPTY', 'ADOPTION_REQUIRED')
               AND NEW.state = 'ACTIVE'
               AND OLD.binding_revision = 0 AND NEW.binding_revision = 1
               AND NEW.singleton_id = OLD.singleton_id
               AND NEW.currency_contract_version = OLD.currency_contract_version
               AND NEW.created_at = OLD.created_at THEN
                RETURN NEW;
            END IF;
            {_DEFAULT_CHANGE if allow_default_change else ''}
            RAISE EXCEPTION 'XPJ_CURRENCY_BINDING: invalid state transition %/% -> %/%',
                OLD.state, OLD.binding_revision, NEW.state, NEW.binding_revision;
        END;
        $$
    """))


def _set_authority_revision(bind, expected: str, target: str) -> None:
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the default currency migration edge")


def upgrade() -> None:
    bind = op.get_bind()
    op.drop_constraint(_ACTION_CHECK, "installation_currency_audit_log", type_="check")
    op.create_check_constraint(_ACTION_CHECK, "installation_currency_audit_log",
        "action IN ('FIRST_FACT_CLAIM', 'OWNER_ADOPTION', 'OWNER_DEFAULT_CHANGE')")
    _install_guard(allow_default_change=True)
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("""SELECT
        EXISTS (SELECT 1 FROM installation_currency_bindings WHERE binding_revision > 1)
        OR EXISTS (SELECT 1 FROM installation_currency_audit_log WHERE action = 'OWNER_DEFAULT_CHANGE')
        OR EXISTS (SELECT 1 FROM installation_idempotency_keys WHERE operation = 'currency_default_change')
    """)):
        raise RuntimeError("cannot erase accepted default currency changes")
    _install_guard(allow_default_change=False)
    op.drop_constraint(_ACTION_CHECK, "installation_currency_audit_log", type_="check")
    op.create_check_constraint(_ACTION_CHECK, "installation_currency_audit_log",
        "action IN ('FIRST_FACT_CLAIM', 'OWNER_ADOPTION')")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind) -> None:
    checks = {check["name"]: check["sqltext"] for check in sa.inspect(bind).get_check_constraints("installation_currency_audit_log")}
    if "OWNER_DEFAULT_CHANGE" not in checks.get(_ACTION_CHECK, ""):
        raise RuntimeError("default currency audit action is missing")
    definition = bind.scalar(sa.text("SELECT pg_get_functiondef(to_regprocedure(:function))"), {"function": f"{_GUARD}()"}) or ""
    if _DEFAULT_CHANGE.strip() not in definition:
        raise RuntimeError("default currency transition guard is missing")
    if bind.scalar(sa.text("""SELECT count(*) FROM pg_trigger WHERE tgrelid='installation_currency_bindings'::regclass
        AND tgname IN ('trg_currency_binding_update_delete', 'trg_currency_binding_truncate')
        AND NOT tgisinternal AND tgenabled='O'""")) != 2:
        raise RuntimeError("default currency transition triggers are missing")

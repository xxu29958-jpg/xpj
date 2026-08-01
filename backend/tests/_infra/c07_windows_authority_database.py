"""Restore-database activation and ACL installation for the real C07 scenario."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

from tests._infra.c07_windows_authority_acl import (
    verify_privilege_sql_rejects_foreign_acl as verify_privilege_sql_rejects_foreign_acl,
)
from tests._infra.c07_windows_authority_roles import AuthorityScenario

_SOURCE_SCHEMA_SQL = """
CREATE TABLE public.accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    public_id uuid NOT NULL UNIQUE,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE public.devices (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES public.accounts(id),
    idempotency_replay_ack_epoch varchar(64),
    idempotency_replay_acknowledged_at timestamptz
);
CREATE TABLE public.app_meta (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key text NOT NULL UNIQUE,
    value text NOT NULL
);
CREATE TABLE public.schema_migrations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    note text
);
CREATE TABLE public.alembic_version (version_num text PRIMARY KEY);
CREATE TABLE public.ledger_audit_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action text NOT NULL
);
CREATE TABLE public.budget_advisor_audit_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    result text NOT NULL
);
CREATE TABLE public.ocr_facts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_text text
);
CREATE TABLE public.ledger_learning_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type text NOT NULL
);
CREATE TABLE public.debt_adjustments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text
);
CREATE TABLE public.debt_forgivenesses (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text
);
CREATE TABLE public.debt_voids (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text
);
CREATE TABLE public.repayment_voids (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text
);
CREATE TABLE public.repayments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text
);
CREATE TABLE public.receipt_authority_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, secret text NOT NULL
);
CREATE TABLE public.api_idempotency_contract_fences (
    tenant_id text NOT NULL,
    idempotency_key text NOT NULL,
    contract_version smallint NOT NULL
        CHECK (contract_version IN (1, 2)),
    claim_count bigint NOT NULL CHECK (claim_count > 0),
    PRIMARY KEY (tenant_id, idempotency_key)
);
CREATE TABLE public.api_idempotency_keys (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id text NOT NULL,
    idempotency_key text NOT NULL,
    key_scope text,
    operation text NOT NULL DEFAULT 'c07_probe',
    target_type text,
    target_id text,
    request_fingerprint text NOT NULL DEFAULT
        'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
    status text NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'succeeded')),
    resource_type text,
    resource_id text,
    contract_version smallint NOT NULL DEFAULT 1
        CHECK (contract_version IN (1, 2)),
    replay_disposition text NOT NULL DEFAULT 'legacy_unreplayable',
    binding_kind text,
    principal_account_id bigint REFERENCES public.accounts(id),
    principal_device_id bigint REFERENCES public.devices(id),
    principal_client_id text,
    replay_policy_epoch varchar(64),
    result_schema text,
    result_http_status smallint,
    result_kind text,
    result_resource_type text,
    result_resource_id text,
    result_post_row_version bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT
        (clock_timestamp() + interval '30 days'),
    CHECK (expires_at >= created_at + interval '30 days')
);
CREATE FUNCTION public.ticketbox_idempotency_contract_fence_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    admitted_version smallint;
    remaining_claims bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.api_idempotency_contract_fences AS fence(
            tenant_id,
            idempotency_key,
            contract_version,
            claim_count
        )
        VALUES (
            NEW.tenant_id,
            NEW.idempotency_key,
            NEW.contract_version,
            1
        )
        ON CONFLICT (tenant_id, idempotency_key)
        DO UPDATE
        SET claim_count = fence.claim_count + 1
        WHERE fence.contract_version = EXCLUDED.contract_version
        RETURNING contract_version INTO admitted_version;
        IF admitted_version IS NULL THEN
            RAISE unique_violation
            USING MESSAGE =
                'idempotency tenant/key is claimed by another contract';
        END IF;
        RETURN NEW;
    END IF;
    DELETE FROM public.api_idempotency_contract_fences
    WHERE tenant_id = OLD.tenant_id
      AND idempotency_key = OLD.idempotency_key
      AND contract_version = OLD.contract_version
      AND claim_count = 1
    RETURNING 0 INTO remaining_claims;
    IF remaining_claims IS NULL THEN
        UPDATE public.api_idempotency_contract_fences
        SET claim_count = claim_count - 1
        WHERE tenant_id = OLD.tenant_id
          AND idempotency_key = OLD.idempotency_key
          AND contract_version = OLD.contract_version
          AND claim_count > 1
        RETURNING claim_count INTO remaining_claims;
    END IF;
    IF remaining_claims IS NULL THEN
        RAISE integrity_constraint_violation
        USING MESSAGE = 'idempotency contract fence count drifted';
    END IF;
    RETURN OLD;
END;
$function$;
REVOKE ALL ON FUNCTION
    public.ticketbox_idempotency_contract_fence_v1()
    FROM PUBLIC;
CREATE TRIGGER trg_api_idempotency_keys_contract_fence
BEFORE INSERT OR DELETE ON public.api_idempotency_keys
FOR EACH ROW
EXECUTE FUNCTION public.ticketbox_idempotency_contract_fence_v1();
CREATE FUNCTION public.ticketbox_idempotency_receipt_transition_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'in_progress'
           OR NEW.completed_at IS NOT NULL
           OR NEW.resource_type IS NOT NULL
           OR NEW.resource_id IS NOT NULL
           OR NEW.result_schema IS NOT NULL
           OR NEW.result_http_status IS NOT NULL
           OR NEW.result_kind IS NOT NULL
           OR NEW.result_resource_type IS NOT NULL
           OR NEW.result_resource_id IS NOT NULL
           OR NEW.result_post_row_version IS NOT NULL
        THEN
            RAISE check_violation
            USING MESSAGE = 'idempotency claim must begin in progress';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW IS NOT DISTINCT FROM OLD THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'succeeded' THEN
        RAISE check_violation
        USING MESSAGE = 'committed idempotency receipt is immutable';
    END IF;
    IF OLD.status <> 'in_progress' THEN
        RAISE check_violation
        USING MESSAGE = 'idempotency transition source is invalid';
    END IF;
    IF ROW(
        NEW.id,
        NEW.tenant_id,
        NEW.key_scope,
        NEW.idempotency_key,
        NEW.operation,
        NEW.target_type,
        NEW.target_id,
        NEW.request_fingerprint,
        NEW.contract_version,
        NEW.replay_disposition,
        NEW.binding_kind,
        NEW.principal_account_id,
        NEW.principal_device_id,
        NEW.principal_client_id
    ) IS DISTINCT FROM ROW(
        OLD.id,
        OLD.tenant_id,
        OLD.key_scope,
        OLD.idempotency_key,
        OLD.operation,
        OLD.target_type,
        OLD.target_id,
        OLD.request_fingerprint,
        OLD.contract_version,
        OLD.replay_disposition,
        OLD.binding_kind,
        OLD.principal_account_id,
        OLD.principal_device_id,
        OLD.principal_client_id
    ) THEN
        RAISE check_violation
        USING MESSAGE = 'idempotency claim identity is immutable';
    END IF;
    IF NEW.status = 'succeeded' AND NEW.completed_at IS NOT NULL THEN
        IF OLD.contract_version = 2 THEN
            IF (
                to_jsonb(NEW) - ARRAY[
                    'status',
                    'completed_at',
                    'result_schema',
                    'result_http_status',
                    'result_kind',
                    'result_resource_type',
                    'result_resource_id',
                    'result_post_row_version'
                ]
            ) IS DISTINCT FROM (
                to_jsonb(OLD) - ARRAY[
                    'status',
                    'completed_at',
                    'result_schema',
                    'result_http_status',
                    'result_kind',
                    'result_resource_type',
                    'result_resource_id',
                    'result_post_row_version'
                ]
            ) THEN
                RAISE check_violation
                USING MESSAGE = 'v2 completion changed claim facts';
            END IF;
        ELSE
            IF (
                to_jsonb(NEW) - ARRAY[
                    'status',
                    'completed_at',
                    'resource_type',
                    'resource_id'
                ]
            ) IS DISTINCT FROM (
                to_jsonb(OLD) - ARRAY[
                    'status',
                    'completed_at',
                    'resource_type',
                    'resource_id'
                ]
            ) THEN
                RAISE check_violation
                USING MESSAGE = 'v1 completion changed claim facts';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.contract_version = 1
       AND NEW.status = 'in_progress'
       AND NEW.created_at > OLD.created_at
       AND NEW.expires_at > OLD.expires_at
       AND (
           to_jsonb(NEW) - ARRAY['created_at', 'expires_at']
       ) IS NOT DISTINCT FROM (
           to_jsonb(OLD) - ARRAY['created_at', 'expires_at']
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE check_violation
    USING MESSAGE = 'idempotency receipt transition is invalid';
END;
$function$;
REVOKE ALL ON FUNCTION
    public.ticketbox_idempotency_receipt_transition_v1()
    FROM PUBLIC;
CREATE TRIGGER trg_api_idempotency_keys_receipt_transition
BEFORE INSERT OR UPDATE ON public.api_idempotency_keys
FOR EACH ROW
EXECUTE FUNCTION public.ticketbox_idempotency_receipt_transition_v1();
CREATE FUNCTION public.ticketbox_idempotency_retention_delete_guard_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $function$
BEGIN
    IF OLD.contract_version <> 2
       OR OLD.replay_disposition <> 'stable_v2'
       OR OLD.status <> 'succeeded'
       OR OLD.completed_at IS NULL
       OR OLD.expires_at >= pg_catalog.statement_timestamp()
       OR OLD.replay_policy_epoch IS NULL
    THEN
        RAISE check_violation
        USING MESSAGE = 'idempotency receipt is not retention eligible';
    END IF;
    IF OLD.binding_kind = 'application'
       AND OLD.principal_account_id IS NOT NULL
       AND OLD.principal_device_id IS NOT NULL
       AND OLD.replay_policy_epoch =
           'ticketbox-idempotency-app-2026-07-v1'
    THEN
        PERFORM 1
        FROM public.devices AS device
        WHERE device.id = OLD.principal_device_id
          AND device.account_id = OLD.principal_account_id
          AND device.idempotency_replay_ack_epoch =
              'ticketbox-idempotency-app-2026-07-v1'
          AND device.idempotency_replay_acknowledged_at IS NOT NULL
        FOR KEY SHARE;
        IF FOUND THEN
            RETURN OLD;
        END IF;
    ELSIF OLD.binding_kind = 'internal'
          AND OLD.principal_client_id = 'owner-console-loopback-v1'
          AND OLD.replay_policy_epoch =
              'ticketbox-idempotency-internal-sync-v1'
    THEN
        RETURN OLD;
    END IF;
    RAISE check_violation
    USING MESSAGE = 'idempotency retention evidence is not trusted';
END;
$function$;
REVOKE ALL ON FUNCTION
    public.ticketbox_idempotency_retention_delete_guard_v1()
    FROM PUBLIC;
CREATE TRIGGER trg_api_idempotency_keys_retention_delete_guard
BEFORE DELETE ON public.api_idempotency_keys
FOR EACH ROW
EXECUTE FUNCTION public.ticketbox_idempotency_retention_delete_guard_v1();
INSERT INTO public.alembic_version(version_num) VALUES ('c07_base');
"""


def create_registered_restore_database(scenario: AuthorityScenario) -> None:
    admin = scenario.admin
    admin.execute(scenario.generated["restore_create"])
    cluster, database_oid, owner_oid, allows = admin.execute(
        "SELECT control.system_identifier::text, database.oid, "
        "database.datdba, database.datallowconn "
        "FROM pg_control_system() AS control "
        "JOIN pg_database AS database ON database.datname = %s",
        (scenario.database,),
    ).fetchone()
    assert allows is False
    assert owner_oid == scenario.role_authority[scenario.owner][0]
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            scenario.conninfo(
                database=scenario.database,
                username=scenario.migrator,
                password=scenario.migrator_password,
            ),
            connect_timeout=5,
        )
    scenario.registered_marker = (
        f"ticketbox-c07-restore-database-v3|{scenario.operation_id}|"
        f"{scenario.restore_attempt_id}|registered|{cluster}|"
        f"{scenario.database}|{database_oid}|{owner_oid}|"
        f"{scenario.role_authority[scenario.migrator][0]}"
    )
    admin.execute(
        sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            sql.Identifier(scenario.database),
            sql.Literal(scenario.registered_marker),
        )
    )


def activate_restore_database(scenario: AuthorityScenario) -> None:
    admin = scenario.admin
    admin.execute(
        sql.SQL("GRANT CONNECT, CREATE, TEMPORARY ON DATABASE {} TO {}").format(
            sql.Identifier(scenario.database),
            sql.Identifier(scenario.outsider),
        )
    )
    scenario.active_marker = scenario.registered_marker.replace(
        "|registered|",
        "|active|",
        1,
    )
    open_sql = scenario.restore_open_sql(
        scenario.tmp_path,
        owner=scenario.owner,
        migrator=scenario.migrator,
        runtime=scenario.runtime,
        database=scenario.database,
        marker=scenario.active_marker,
    )
    admin.execute(open_sql)
    row = admin.execute(
        "SELECT datallowconn, shobj_description(oid, 'pg_database') = %s, "
        "NOT has_database_privilege(%s, datname, 'CONNECT'), "
        "NOT has_database_privilege(%s, datname, 'CONNECT'), "
        "NOT (has_database_privilege(%s, datname, 'CONNECT') OR "
        "has_database_privilege(%s, datname, 'CREATE') OR "
        "has_database_privilege(%s, datname, 'TEMPORARY')) "
        "FROM pg_database WHERE datname = %s",
        (
            scenario.active_marker,
            scenario.migrator,
            scenario.runtime,
            scenario.outsider,
            scenario.outsider,
            scenario.outsider,
            scenario.database,
        ),
    ).fetchone()
    assert row == (True, True, True, True, True)
    for role, password in (
        (scenario.runtime, scenario.runtime_password),
        (scenario.migrator, scenario.migrator_password),
    ):
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                scenario.conninfo(
                    database=scenario.database,
                    username=role,
                    password=password,
                ),
                connect_timeout=5,
            )


def install_source_schema(scenario: AuthorityScenario) -> None:
    scenario.database_admin = psycopg.connect(
        scenario.conninfo(database=scenario.database),
        autocommit=True,
    )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="foreign active session",
    ):
        scenario.admin.execute(
            scenario.restore_open_sql(
                scenario.tmp_path,
                owner=scenario.owner,
                migrator=scenario.migrator,
                runtime=scenario.runtime,
                database=scenario.database,
                marker=scenario.active_marker,
            )
        )
    scenario.admin.execute("ROLLBACK")
    scenario.database_admin.execute(
        sql.SQL("SET ROLE {}").format(sql.Identifier(scenario.owner))
    )
    scenario.database_admin.execute(_SOURCE_SCHEMA_SQL)
    scenario.database_admin.execute("RESET ROLE")

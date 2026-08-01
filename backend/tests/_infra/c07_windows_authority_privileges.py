"""Runtime/migrator privilege and retirement phases for real C07 PostgreSQL."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

from tests._infra.c07_windows_authority_idempotency import (
    verify_runtime_idempotency_acl,
)
from tests._infra.c07_windows_authority_roles import AuthorityScenario


def open_authority_connections(scenario: AuthorityScenario) -> None:
    scenario.migrator_connection = psycopg.connect(
        scenario.conninfo(
            database=scenario.database,
            username=scenario.migrator,
            password=scenario.migrator_password,
        ),
        autocommit=True,
    )
    scenario.runtime_connection = psycopg.connect(
        scenario.conninfo(
            database=scenario.database,
            username=scenario.runtime,
            password=scenario.runtime_password,
        ),
        autocommit=True,
    )
    for role, password in (
        (scenario.runtime, scenario.foreign_runtime_password),
        (scenario.migrator, scenario.foreign_migrator_password),
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


def verify_runtime_business_acl(scenario: AuthorityScenario) -> None:
    runtime = scenario.runtime_connection
    database_admin = scenario.database_admin
    assert runtime is not None and database_admin is not None
    account_id = runtime.execute(
        "INSERT INTO public.accounts(public_id, display_name, created_at) "
        "VALUES (%s, 'C07 runtime', clock_timestamp()) RETURNING id",
        (scenario.operation_id,),
    ).fetchone()[0]
    runtime.execute(
        "UPDATE public.accounts SET display_name = 'updated' WHERE id = %s",
        (account_id,),
    )
    runtime.execute("DELETE FROM public.accounts WHERE id = %s", (account_id,))
    runtime.execute(
        "INSERT INTO public.app_meta(key, value) VALUES ('authority', 'one')"
    )
    runtime.execute(
        "UPDATE public.app_meta SET value = 'two' WHERE key = 'authority'"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("DELETE FROM public.app_meta WHERE key = 'authority'")
    runtime.execute(
        "INSERT INTO public.schema_migrations(name, note) "
        "VALUES ('runtime-seed', 'append only')"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("UPDATE public.schema_migrations SET note = 'mutated'")
    runtime.execute("INSERT INTO public.ledger_audit_logs(action) VALUES ('created')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("UPDATE public.ledger_audit_logs SET action = 'rewritten'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("DELETE FROM public.ledger_audit_logs")
    ocr_fact_id = runtime.execute(
        "INSERT INTO public.ocr_facts(raw_text) VALUES ('fact') RETURNING id"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("UPDATE public.ocr_facts SET raw_text = 'rewritten'")
    runtime.execute("DELETE FROM public.ocr_facts WHERE id = %s", (ocr_fact_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("UPDATE public.alembic_version SET version_num = 'forged'")
    verify_runtime_idempotency_acl(scenario)


def verify_runtime_financial_facts(scenario: AuthorityScenario) -> None:
    runtime = scenario.runtime_connection
    assert runtime is not None
    for table in (
        "debt_adjustments",
        "debt_forgivenesses",
        "debt_voids",
        "repayment_voids",
        "repayments",
    ):
        runtime.execute(
            sql.SQL("INSERT INTO public.{} DEFAULT VALUES").format(
                sql.Identifier(table)
            )
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                sql.SQL("UPDATE public.{} SET note = 'mutated'").format(
                    sql.Identifier(table)
                )
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                sql.SQL("DELETE FROM public.{}").format(sql.Identifier(table))
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                sql.SQL("TRUNCATE TABLE public.{}").format(sql.Identifier(table))
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("SELECT * FROM public.receipt_authority_records")


def verify_future_objects_are_narrow(scenario: AuthorityScenario) -> None:
    migrator = scenario.migrator_connection
    runtime = scenario.runtime_connection
    database_admin = scenario.database_admin
    assert migrator is not None and runtime is not None and database_admin is not None
    migrator.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(scenario.owner)))
    migrator.execute(
        "CREATE TABLE public.c07_future_authority(id bigint); "
        "CREATE FUNCTION public.c07_future_definer() RETURNS bigint "
        "LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog "
        "AS $$ SELECT 1::bigint $$; "
        "CREATE PROCEDURE public.c07_future_procedure() LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = pg_catalog "
        "AS $$ BEGIN NULL; END $$; "
        "CREATE TABLE public.c07_pre_ready_ddl(id bigint);"
    )
    migrator.execute("RESET ROLE")
    future_acl = database_admin.execute(
        "SELECT pg_get_userbyid(proowner), proacl, "
        "has_function_privilege(%s, oid, 'EXECUTE') FROM pg_proc "
        "WHERE oid = 'public.c07_future_definer()'::regprocedure",
        (scenario.runtime,),
    ).fetchone()
    assert future_acl[2] is False, future_acl
    for statement in (
        "SELECT * FROM public.c07_future_authority",
        "SELECT public.c07_future_definer()",
        "CALL public.c07_future_procedure()",
        "CREATE TABLE public.runtime_ddl(id bigint)",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(statement)
    assert runtime.execute(
        "SELECT count(*) FROM public.app_meta WHERE key = 'authority_ready'"
    ).fetchone() == (0,)


def retire_migrator(scenario: AuthorityScenario) -> None:
    database_admin = scenario.database_admin
    runtime = scenario.runtime_connection
    migrator = scenario.migrator_connection
    assert database_admin is not None and runtime is not None and migrator is not None
    database_admin.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(scenario.outsider),
            sql.Identifier(scenario.migrator),
        )
    )
    database_admin.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(scenario.migrator),
            sql.Identifier(scenario.outsider_member),
        )
    )
    database_admin.execute(scenario.generated["retirement"])
    database_admin.execute(scenario.generated["retirement_verification"])
    with pytest.raises(psycopg.Error):
        migrator.execute("CREATE TABLE public.c07_old_session_ddl(id bigint)")
    migrator.close()
    scenario.migrator_connection = None
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            scenario.conninfo(
                database=scenario.database,
                username=scenario.migrator,
                password=scenario.migrator_password,
            ),
            connect_timeout=5,
        )
    retired = scenario.admin.execute(
        "SELECT NOT role.rolcanlogin AND role.rolpassword IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM pg_auth_members AS membership "
        "WHERE membership.roleid = role.oid OR membership.member = role.oid) "
        "AND NOT EXISTS (SELECT 1 FROM pg_stat_activity "
        "WHERE usename = role.rolname) FROM pg_authid AS role "
        "WHERE role.rolname = %s",
        (scenario.migrator,),
    ).fetchone()
    assert retired == (True,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("CREATE TABLE public.runtime_after_retirement(id bigint)")

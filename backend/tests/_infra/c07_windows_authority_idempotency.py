"""Idempotency receipt authority checks for the real C07 scenario."""

from __future__ import annotations

from collections.abc import Iterable

import psycopg
import pytest
from psycopg import sql

from tests._infra.c07_windows_authority_roles import AuthorityScenario

_RetentionClaim = tuple[
    str,
    str,
    str,
    int | None,
    int | None,
    str | None,
    str,
    str,
    str,
]


def _seed_shared_contract_claims(
    runtime: psycopg.Connection,
    database_admin: psycopg.Connection,
) -> None:
    runtime.execute(
        "INSERT INTO public.api_idempotency_keys("
        "tenant_id, idempotency_key"
        ") VALUES "
        "('ledger-runtime-fence', 'shared-contract'), "
        "('ledger-runtime-fence', 'shared-contract')"
    )
    assert database_admin.execute(
        "SELECT contract_version, claim_count "
        "FROM public.api_idempotency_contract_fences "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'"
    ).fetchone() == (1, 2)


def _assert_fence_routine_shapes(
    scenario: AuthorityScenario,
    database_admin: psycopg.Connection,
) -> None:
    routine_shape = database_admin.execute(
        "SELECT routine.prosecdef, routine.proconfig, "
        "pg_get_userbyid(routine.proowner), "
        "has_function_privilege(%s, routine.oid, 'EXECUTE') "
        "FROM pg_proc AS routine "
        "WHERE routine.oid = "
        "'public.ticketbox_idempotency_contract_fence_v1()'::regprocedure",
        (scenario.runtime,),
    ).fetchone()
    assert routine_shape is not None
    assert routine_shape[0] is True
    assert tuple(routine_shape[1] or ()) == (
        "search_path=pg_catalog, pg_temp",
    )
    assert routine_shape[2:] == (scenario.owner, False)
    transition_shapes = database_admin.execute(
        "SELECT routine.proname, routine.prosecdef, routine.proconfig, "
        "pg_get_userbyid(routine.proowner), "
        "has_function_privilege(%s, routine.oid, 'EXECUTE') "
        "FROM pg_proc AS routine "
        "WHERE routine.proname IN ("
        "'ticketbox_idempotency_receipt_transition_v1', "
        "'ticketbox_idempotency_retention_delete_guard_v1'"
        ") ORDER BY routine.proname",
        (scenario.runtime,),
    ).fetchall()
    assert len(transition_shapes) == 2
    for _name, security_definer, config, owner, runtime_execute in (
        transition_shapes
    ):
        assert security_definer is False
        assert tuple(config or ()) == (
            "search_path=pg_catalog, pg_temp",
        )
        assert (owner, runtime_execute) == (scenario.owner, False)


def _assert_fence_is_not_directly_accessible(
    runtime: psycopg.Connection,
) -> None:
    for statement in (
        "SELECT * FROM public.api_idempotency_contract_fences",
        "INSERT INTO public.api_idempotency_contract_fences("
        "tenant_id, idempotency_key, contract_version, claim_count"
        ") VALUES ('direct', 'forbidden', 1, 1)",
        "UPDATE public.api_idempotency_contract_fences "
        "SET claim_count = claim_count",
        "DELETE FROM public.api_idempotency_contract_fences",
        "SELECT public.ticketbox_idempotency_contract_fence_v1()",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(statement)


def _complete_and_lock_shared_contract_claims(
    runtime: psycopg.Connection,
) -> None:
    runtime.execute(
        "UPDATE public.api_idempotency_keys "
        "SET status = 'succeeded', completed_at = clock_timestamp(), "
        "resource_type = 'probe', resource_id = '1' "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'"
    )
    for statement in (
        "UPDATE public.api_idempotency_keys "
        "SET resource_id = 'forged' "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'",
        "UPDATE public.api_idempotency_keys "
        "SET status = 'in_progress', completed_at = NULL, "
        "resource_type = NULL, resource_id = NULL "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'",
        "UPDATE public.api_idempotency_keys "
        "SET request_fingerprint = repeat('0', 64) "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'",
        "DELETE FROM public.api_idempotency_keys "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            runtime.execute(statement)
    with pytest.raises(psycopg.errors.CheckViolation):
        runtime.execute(
            "INSERT INTO public.api_idempotency_keys("
            "tenant_id, idempotency_key, status, completed_at, "
            "resource_type, resource_id"
            ") VALUES ("
            "'ledger-runtime-fence', 'direct-terminal', 'succeeded', "
            "clock_timestamp(), 'probe', '1'"
            ")"
        )


def _create_retention_principals(
    scenario: AuthorityScenario,
    runtime: psycopg.Connection,
) -> tuple[int, int, int]:
    retention_account = runtime.execute(
        "INSERT INTO public.accounts(public_id, display_name, created_at) "
        "VALUES (%s, 'retention runtime', clock_timestamp()) RETURNING id",
        (
            "10000000-0000-4000-8000-"
            f"{scenario.operation_id.replace('-', '')[:12]}",
        ),
    ).fetchone()[0]
    acknowledged_device = runtime.execute(
        "INSERT INTO public.devices("
        "account_id, idempotency_replay_ack_epoch, "
        "idempotency_replay_acknowledged_at"
        ") VALUES (%s, 'ticketbox-idempotency-app-2026-07-v1', "
        "clock_timestamp()) RETURNING id",
        (retention_account,),
    ).fetchone()[0]
    unacknowledged_device = runtime.execute(
        "INSERT INTO public.devices(account_id) VALUES (%s) RETURNING id",
        (retention_account,),
    ).fetchone()[0]
    return retention_account, acknowledged_device, unacknowledged_device


def _retention_claims(
    retention_account: int,
    acknowledged_device: int,
    unacknowledged_device: int,
) -> tuple[_RetentionClaim, ...]:
    return (
        (
            "eligible-internal",
            "client:owner-console-loopback-v1",
            "internal",
            None,
            None,
            "owner-console-loopback-v1",
            "ticketbox-idempotency-internal-sync-v1",
            "-31 days",
            "-1 day",
        ),
        (
            "eligible-application",
            f"account:{retention_account}",
            "application",
            retention_account,
            acknowledged_device,
            None,
            "ticketbox-idempotency-app-2026-07-v1",
            "-31 days",
            "-1 day",
        ),
        (
            "unacked-application",
            f"account:{retention_account}",
            "application",
            retention_account,
            unacknowledged_device,
            None,
            "ticketbox-idempotency-app-2026-07-v1",
            "-31 days",
            "-1 day",
        ),
        (
            "future-internal",
            "client:owner-console-loopback-v1",
            "internal",
            None,
            None,
            "owner-console-loopback-v1",
            "ticketbox-idempotency-internal-sync-v1",
            "0 days",
            "30 days",
        ),
        (
            "nonallowlisted-internal",
            "client:foreign-worker",
            "internal",
            None,
            None,
            "foreign-worker",
            "foreign-epoch",
            "-31 days",
            "-1 day",
        ),
    )


def _seed_retention_claims(
    runtime: psycopg.Connection,
    claims: Iterable[_RetentionClaim],
) -> None:
    for (
        key,
        key_scope,
        binding_kind,
        principal_account_id,
        principal_device_id,
        principal_client_id,
        replay_epoch,
        created_delta,
        expires_delta,
    ) in claims:
        runtime.execute(
            "INSERT INTO public.api_idempotency_keys("
            "tenant_id, key_scope, idempotency_key, contract_version, "
            "replay_disposition, binding_kind, principal_account_id, "
            "principal_device_id, principal_client_id, "
            "replay_policy_epoch, created_at, expires_at"
            ") VALUES ("
            "'ledger-runtime-retention', %s, %s, 2, 'stable_v2', %s, "
            "%s, %s, %s, %s, "
            "clock_timestamp() + %s::interval, "
            "clock_timestamp() + %s::interval"
            ")",
            (
                key_scope,
                key,
                binding_kind,
                principal_account_id,
                principal_device_id,
                principal_client_id,
                replay_epoch,
                created_delta,
                expires_delta,
            ),
        )
        runtime.execute(
            "UPDATE public.api_idempotency_keys SET "
            "status = 'succeeded', completed_at = clock_timestamp(), "
            "result_schema = 'idempotency_committed_success_v2', "
            "result_http_status = 200, "
            "result_kind = 'operation_committed', "
            "result_resource_type = 'probe', "
            "result_resource_id = %s "
            "WHERE idempotency_key = %s",
            (key, key),
        )


def _verify_retention_guards(
    runtime: psycopg.Connection,
    database_admin: psycopg.Connection,
) -> None:
    for key in (
        "unacked-application",
        "future-internal",
        "nonallowlisted-internal",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            runtime.execute(
                "DELETE FROM public.api_idempotency_keys "
                "WHERE idempotency_key = %s",
                (key,),
            )
    runtime.execute(
        "DELETE FROM public.api_idempotency_keys "
        "WHERE idempotency_key IN "
        "('eligible-internal', 'eligible-application')"
    )
    assert database_admin.execute(
        "SELECT count(*) FROM public.api_idempotency_keys "
        "WHERE idempotency_key IN "
        "('eligible-internal', 'eligible-application')"
    ).fetchone() == (0,)


def _break_glass_cleanup(
    scenario: AuthorityScenario,
    database_admin: psycopg.Connection,
) -> None:
    database_admin.execute(
        sql.SQL("SET ROLE {}").format(sql.Identifier(scenario.owner))
    )
    try:
        # Table ownership is not a retention-policy bypass. Break-glass
        # cleanup must be an explicit, auditable DDL action.
        database_admin.execute(
            "ALTER TABLE public.api_idempotency_keys "
            "DISABLE TRIGGER "
            "trg_api_idempotency_keys_retention_delete_guard"
        )
        try:
            database_admin.execute(
                "DELETE FROM public.api_idempotency_keys "
                "WHERE tenant_id IN ('ledger-runtime-fence', "
                "'ledger-runtime-retention')"
            )
        finally:
            database_admin.execute(
                "ALTER TABLE public.api_idempotency_keys "
                "ENABLE TRIGGER "
                "trg_api_idempotency_keys_retention_delete_guard"
            )
    finally:
        database_admin.execute("RESET ROLE")
    assert database_admin.execute(
        "SELECT count(*) FROM public.api_idempotency_contract_fences "
        "WHERE tenant_id = 'ledger-runtime-fence' "
        "AND idempotency_key = 'shared-contract'"
    ).fetchone() == (0,)


def verify_runtime_idempotency_acl(scenario: AuthorityScenario) -> None:
    runtime = scenario.runtime_connection
    database_admin = scenario.database_admin
    assert runtime is not None and database_admin is not None
    _seed_shared_contract_claims(runtime, database_admin)
    _assert_fence_routine_shapes(scenario, database_admin)
    _assert_fence_is_not_directly_accessible(runtime)
    _complete_and_lock_shared_contract_claims(runtime)
    principals = _create_retention_principals(scenario, runtime)
    _seed_retention_claims(runtime, _retention_claims(*principals))
    _verify_retention_guards(runtime, database_admin)
    _break_glass_cleanup(scenario, database_admin)

"""Seal PostgreSQL runtime access to authority tables and upgrade attestation."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.app_meta_observation import MANAGED_UPGRADE_ATTESTATION_KEY
from app.database._managed_postgres_contract import RUNTIME_READ_ONLY_TABLES, RUNTIME_ROLE

_QUALIFIED_TABLES = ", ".join(f'public."{name}"' for name in RUNTIME_READ_ONLY_TABLES)
_TABLE_NAMES = ", ".join(f"'{name}'" for name in RUNTIME_READ_ONLY_TABLES)
_ROLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_ATTESTATION_GUARD_FUNCTION = "ticketbox_guard_upgrade_attestation"
_ATTESTATION_GUARD_TRIGGER = "trg_ticketbox_guard_upgrade_attestation"


def seal_runtime_authority_tables(connection: Connection) -> bool:
    connection.execute(
        text(
            "REVOKE INSERT, UPDATE, DELETE ON TABLE "
            f"{_QUALIFIED_TABLES} FROM {RUNTIME_ROLE}"
        )
    )
    return connection.scalar(
        text(
            "SELECT count(*) = 2 AND bool_and("
            f"has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'SELECT') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'INSERT') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'UPDATE') "
            f"AND NOT has_table_privilege('{RUNTIME_ROLE}', relation.oid, 'DELETE')) "
            "FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = 'public' "
            f"AND relation.relname IN ({_TABLE_NAMES})"
        )
    ) is True


def seal_upgrade_attestation_guard(
    connection: Connection,
    *,
    owner_role: str | None = None,
) -> bool:
    if connection.scalar(text("SELECT to_regclass('public.app_meta')")) is None:
        return True
    resolved_owner = owner_role or connection.scalar(
        text(
            "SELECT pg_catalog.pg_get_userbyid(relation.relowner) "
            "FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = 'public' AND relation.relname = 'app_meta'"
        )
    )
    if not isinstance(resolved_owner, str) or _ROLE_NAME.fullmatch(resolved_owner) is None:
        return False
    connection.execute(
        text(
            f"CREATE OR REPLACE FUNCTION public.{_ATTESTATION_GUARD_FUNCTION}() "
            "RETURNS trigger "
            "LANGUAGE plpgsql "
            "SET search_path = pg_catalog "
            "AS $ticketbox_guard$ "
            "BEGIN "
            f"IF current_user <> '{resolved_owner}' AND ("
            f"(TG_OP IN ('INSERT', 'UPDATE') AND NEW.key = '{MANAGED_UPGRADE_ATTESTATION_KEY}') "
            f"OR (TG_OP IN ('UPDATE', 'DELETE') AND OLD.key = '{MANAGED_UPGRADE_ATTESTATION_KEY}')"
            ") THEN "
            f"RAISE EXCEPTION '{MANAGED_UPGRADE_ATTESTATION_KEY} is read-only for role %', current_user "
            "USING ERRCODE = '42501'; "
            "END IF; "
            "IF TG_OP = 'DELETE' THEN "
            "RETURN OLD; "
            "END IF; "
            "RETURN NEW; "
            "END; "
            "$ticketbox_guard$"
        )
    )
    connection.execute(
        text(f"REVOKE ALL ON FUNCTION public.{_ATTESTATION_GUARD_FUNCTION}() FROM PUBLIC")
    )
    connection.execute(
        text(f"DROP TRIGGER IF EXISTS {_ATTESTATION_GUARD_TRIGGER} ON public.app_meta")
    )
    connection.execute(
        text(
            f"CREATE TRIGGER {_ATTESTATION_GUARD_TRIGGER} "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.app_meta "
            f"FOR EACH ROW EXECUTE FUNCTION public.{_ATTESTATION_GUARD_FUNCTION}()"
        )
    )
    return connection.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 "
            "FROM pg_catalog.pg_trigger AS trg "
            "JOIN pg_catalog.pg_class AS rel ON rel.oid = trg.tgrelid "
            "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace "
            "JOIN pg_catalog.pg_proc AS fn ON fn.oid = trg.tgfoid "
            "JOIN pg_catalog.pg_namespace AS fn_ns ON fn_ns.oid = fn.pronamespace "
            "WHERE ns.nspname = 'public' "
            "AND rel.relname = 'app_meta' "
            "AND NOT trg.tgisinternal "
            "AND trg.tgname = :trigger_name "
            "AND trg.tgenabled = 'O' "
            "AND trg.tgtype = 31 "
            "AND trg.tgqual IS NULL "
            "AND trg.tgattr = ''::int2vector "
            "AND fn_ns.nspname = 'public' "
            "AND fn.proname = :function_name "
            "AND pg_catalog.pg_get_userbyid(rel.relowner) = :owner_role "
            "AND pg_catalog.pg_get_userbyid(fn.proowner) = :owner_role"
            ")"
        ),
        {
            "trigger_name": _ATTESTATION_GUARD_TRIGGER,
            "function_name": _ATTESTATION_GUARD_FUNCTION,
            "owner_role": resolved_owner,
        },
    ) is True


__all__ = ["seal_runtime_authority_tables", "seal_upgrade_attestation_guard"]

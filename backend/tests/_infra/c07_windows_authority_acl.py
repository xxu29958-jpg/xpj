"""Foreign-ACL rejection checks for the real C07 PostgreSQL scenario."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

from tests._infra.c07_windows_authority_roles import AuthorityScenario


def verify_privilege_sql_rejects_foreign_acl(
    scenario: AuthorityScenario,
) -> None:
    database_admin = scenario.database_admin
    assert database_admin is not None
    database_admin.execute(
        sql.SQL("GRANT SELECT ON public.accounts TO {}").format(
            sql.Identifier(scenario.outsider)
        )
    )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="foreign ACL grantee",
    ):
        database_admin.execute(scenario.generated["privilege"])
    database_admin.execute("ROLLBACK")
    database_admin.execute(
        sql.SQL("REVOKE ALL ON public.accounts FROM {}").format(
            sql.Identifier(scenario.outsider)
        )
    )
    database_admin.execute("GRANT SELECT ON public.accounts TO PUBLIC")
    database_admin.execute(scenario.generated["privilege"])
    no_public_acl = database_admin.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM pg_class AS relation, "
        "LATERAL aclexplode(COALESCE(relation.relacl, "
        "acldefault('r', relation.relowner))) AS acl "
        "WHERE relation.oid = 'public.accounts'::regclass AND acl.grantee = 0)"
    ).fetchone()
    assert no_public_acl == (True,)

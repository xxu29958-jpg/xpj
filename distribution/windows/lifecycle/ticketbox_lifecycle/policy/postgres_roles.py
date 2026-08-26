"""Ticketbox PostgreSQL role policy for first-install.

Names match backend ``_managed_postgres_contract``: owner is NOLOGIN,
migrator is the short-lived LOGIN that may SET ROLE owner, runtime is DML only.
Architecture 7.3 calls the middle role maintenance; the installed product name
is ``ticketbox_migrator``.
"""

from __future__ import annotations

DATABASE_NAME = "ticketbox"
OWNER_ROLE = "ticketbox_owner"
MIGRATOR_ROLE = "ticketbox_migrator"
RUNTIME_ROLE = "ticketbox_runtime"

_ROLE_FLAGS = "NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


def provision_statements(*, migrator_password: str, runtime_password: str) -> tuple[str, ...]:
    migrator = _escape_literal(migrator_password)
    runtime = _escape_literal(runtime_password)
    return (
        (
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            f"'{OWNER_ROLE}') THEN CREATE ROLE {OWNER_ROLE} NOLOGIN {_ROLE_FLAGS}; "
            "END IF; END $$;"
        ),
        (
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            f"'{MIGRATOR_ROLE}') THEN CREATE ROLE {MIGRATOR_ROLE} LOGIN {_ROLE_FLAGS} "
            f"CONNECTION LIMIT 1 PASSWORD '{migrator}'; END IF; END $$;"
        ),
        (
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            f"'{RUNTIME_ROLE}') THEN CREATE ROLE {RUNTIME_ROLE} LOGIN {_ROLE_FLAGS} "
            f"PASSWORD '{runtime}'; END IF; END $$;"
        ),
        f"ALTER ROLE {MIGRATOR_ROLE} LOGIN {_ROLE_FLAGS} CONNECTION LIMIT 1 PASSWORD '{migrator}';",
        f"ALTER ROLE {RUNTIME_ROLE} LOGIN {_ROLE_FLAGS} PASSWORD '{runtime}';",
        f"GRANT {OWNER_ROLE} TO {MIGRATOR_ROLE} WITH INHERIT FALSE, SET TRUE;",
    )


def database_exists_sql() -> str:
    return f"SELECT 1 FROM pg_database WHERE datname = '{DATABASE_NAME}'"


def create_database_sql() -> str:
    return f"CREATE DATABASE {DATABASE_NAME} OWNER {OWNER_ROLE} ENCODING 'UTF8';"


def database_connect_statements() -> tuple[str, ...]:
    return (
        f"REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE {DATABASE_NAME} FROM PUBLIC;",
        f"GRANT CONNECT ON DATABASE {DATABASE_NAME} TO {MIGRATOR_ROLE};",
        f"GRANT CONNECT ON DATABASE {DATABASE_NAME} TO {RUNTIME_ROLE};",
    )


def schema_privilege_statements() -> tuple[str, ...]:
    return (
        f"ALTER SCHEMA public OWNER TO {OWNER_ROLE};",
        "REVOKE ALL ON SCHEMA public FROM PUBLIC;",
        f"GRANT USAGE ON SCHEMA public TO {MIGRATOR_ROLE};",
        f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE};",
        # PostgreSQL grants PUBLIC EXECUTE on newly-created functions by
        # default. This must be revoked globally; an IN SCHEMA revoke cannot
        # undo a global default grant.
        (
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;"
        ),
        # DEFAULT PRIVILEGES apply to objects created by owner after this point
        # (Alembic). They grant runtime DML, not migrator SELECT. Migrator reads
        # owner tables only via SET ROLE (INHERIT FALSE, SET TRUE).
        (
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {RUNTIME_ROLE};"
        ),
        (
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {RUNTIME_ROLE};"
        ),
        (
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA public "
            f"GRANT EXECUTE ON FUNCTIONS TO {RUNTIME_ROLE};"
        ),
    )


def verify_roles_sql() -> str:
    return (
        "SELECT rolname || ':' || rolcanlogin::text FROM pg_roles "
        f"WHERE rolname IN ('{OWNER_ROLE}','{MIGRATOR_ROLE}','{RUNTIME_ROLE}') "
        "ORDER BY 1"
    )


def verify_membership_sql() -> str:
    return (
        "SELECT granted.rolname || ':' || member.rolname || ':' || "
        "membership.inherit_option::text || ':' || membership.set_option::text "
        "FROM pg_auth_members AS membership "
        "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
        "JOIN pg_roles AS member ON member.oid = membership.member "
        f"WHERE granted.rolname = '{OWNER_ROLE}' AND member.rolname = '{MIGRATOR_ROLE}'"
    )


def verify_database_privileges_sql() -> str:
    return f"""
WITH roles AS (
  SELECT
    (SELECT oid FROM pg_roles WHERE rolname = '{OWNER_ROLE}') AS owner_oid,
    (SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') AS runtime_oid,
    (SELECT oid FROM pg_roles WHERE rolname = '{MIGRATOR_ROLE}') AS migrator_oid
), public_schema AS (
  SELECT oid, nspowner FROM pg_namespace WHERE nspname = 'public'
)
SELECT (
  (SELECT datdba = roles.owner_oid FROM pg_database, roles WHERE datname = '{DATABASE_NAME}')
  AND NOT has_database_privilege('public', '{DATABASE_NAME}', 'CONNECT')
  AND NOT has_database_privilege('public', '{DATABASE_NAME}', 'CREATE')
  AND NOT has_database_privilege('public', '{DATABASE_NAME}', 'TEMPORARY')
  AND has_database_privilege('{MIGRATOR_ROLE}', '{DATABASE_NAME}', 'CONNECT')
  AND NOT has_database_privilege('{MIGRATOR_ROLE}', '{DATABASE_NAME}', 'CREATE')
  AND NOT has_database_privilege('{MIGRATOR_ROLE}', '{DATABASE_NAME}', 'TEMPORARY')
  AND has_database_privilege('{RUNTIME_ROLE}', '{DATABASE_NAME}', 'CONNECT')
  AND NOT has_database_privilege('{RUNTIME_ROLE}', '{DATABASE_NAME}', 'CREATE')
  AND NOT has_database_privilege('{RUNTIME_ROLE}', '{DATABASE_NAME}', 'TEMPORARY')
  AND (SELECT nspowner = roles.owner_oid FROM public_schema, roles)
  AND NOT has_schema_privilege('public', 'public', 'USAGE')
  AND NOT has_schema_privilege('public', 'public', 'CREATE')
  AND has_schema_privilege('{MIGRATOR_ROLE}', 'public', 'USAGE')
  AND NOT has_schema_privilege('{MIGRATOR_ROLE}', 'public', 'CREATE')
  AND has_schema_privilege('{RUNTIME_ROLE}', 'public', 'USAGE')
  AND NOT has_schema_privilege('{RUNTIME_ROLE}', 'public', 'CREATE')
  AND EXISTS (
    SELECT 1
    FROM pg_default_acl AS defaults, roles
    WHERE defaults.defaclrole = roles.owner_oid
      AND defaults.defaclnamespace = 0
      AND defaults.defaclobjtype = 'f'
      AND NOT EXISTS (
        SELECT 1
        FROM aclexplode(defaults.defaclacl) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
      )
  )
  AND NOT EXISTS (
    SELECT 1
    FROM pg_default_acl AS defaults, roles, public_schema,
         LATERAL aclexplode(defaults.defaclacl) AS acl
    WHERE defaults.defaclrole = roles.owner_oid
      AND defaults.defaclnamespace = public_schema.oid
      AND acl.grantee = 0
  )
  AND 4 = (
    SELECT count(*)
    FROM pg_default_acl AS defaults, roles, public_schema,
         LATERAL aclexplode(defaults.defaclacl) AS acl
    WHERE defaults.defaclrole = roles.owner_oid
      AND defaults.defaclnamespace = public_schema.oid
      AND defaults.defaclobjtype = 'r'
      AND acl.grantee = roles.runtime_oid
      AND acl.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
  )
  AND 2 = (
    SELECT count(*)
    FROM pg_default_acl AS defaults, roles, public_schema,
         LATERAL aclexplode(defaults.defaclacl) AS acl
    WHERE defaults.defaclrole = roles.owner_oid
      AND defaults.defaclnamespace = public_schema.oid
      AND defaults.defaclobjtype = 'S'
      AND acl.grantee = roles.runtime_oid
      AND acl.privilege_type IN ('USAGE', 'SELECT')
  )
  AND 1 = (
    SELECT count(*)
    FROM pg_default_acl AS defaults, roles, public_schema,
         LATERAL aclexplode(defaults.defaclacl) AS acl
    WHERE defaults.defaclrole = roles.owner_oid
      AND defaults.defaclnamespace = public_schema.oid
      AND defaults.defaclobjtype = 'f'
      AND acl.grantee = roles.runtime_oid
      AND acl.privilege_type = 'EXECUTE'
  )
)::text AS ticketbox_privileges_ready
""".strip()


def expected_roles_probe() -> str:
    return f"{MIGRATOR_ROLE}:true\n{OWNER_ROLE}:false\n{RUNTIME_ROLE}:true"


def expected_membership_probe() -> str:
    return f"{OWNER_ROLE}:{MIGRATOR_ROLE}:false:true"


def verify_alembic_version_sql(target_revision: str) -> str:
    # PostgreSQL GRANT … WITH INHERIT FALSE, SET TRUE: migrator cannot SELECT
    # owner-created tables as itself. Official SET ROLE is the probe.
    target = _escape_literal(target_revision)
    return (
        f"SET ROLE {OWNER_ROLE}; "
        "SELECT CASE WHEN count(*) = 1 "
        f"AND min(version_num) = '{target}' "
        f"AND max(version_num) = '{target}' "
        "THEN 'ticketbox-alembic-exact' "
        "ELSE 'ticketbox-alembic-mismatch' END "
        "FROM alembic_version"
    )


def expected_alembic_probe() -> str:
    return "ticketbox-alembic-exact"

from ticketbox_lifecycle.policy.postgres_roles import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    OWNER_ROLE,
    RUNTIME_ROLE,
    create_database_sql,
    database_exists_sql,
    expected_membership_probe,
    expected_roles_probe,
    provision_statements,
    schema_privilege_statements,
    verify_database_privileges_sql,
)


def test_role_names_match_installed_product_contract() -> None:
    assert DATABASE_NAME == "ticketbox"
    assert OWNER_ROLE == "ticketbox_owner"
    assert MIGRATOR_ROLE == "ticketbox_migrator"
    assert RUNTIME_ROLE == "ticketbox_runtime"
    sql = "\n".join(provision_statements(migrator_password="x", runtime_password="y"))
    assert "NOLOGIN" in sql
    assert "INHERIT FALSE, SET TRUE" in sql
    assert "ticketbox_backup" not in sql
    assert create_database_sql() == "CREATE DATABASE ticketbox OWNER ticketbox_owner ENCODING 'UTF8';"
    assert "ticketbox" in database_exists_sql()
    assert expected_roles_probe().splitlines() == [
        "ticketbox_migrator:true",
        "ticketbox_owner:false",
        "ticketbox_runtime:true",
    ]
    assert expected_membership_probe() == "ticketbox_owner:ticketbox_migrator:false:true"
    privilege_probe = verify_database_privileges_sql()
    assert "ticketbox_privileges_ready" in privilege_probe
    assert "pg_default_acl" in privilege_probe
    assert "NOT has_schema_privilege('ticketbox_runtime', 'public', 'CREATE')" in privilege_probe
    assert "defaults.defaclnamespace = 0" in privilege_probe
    assert "acl.grantee = 0" in privilege_probe


def test_function_default_privileges_revoke_public_globally_before_runtime_grant() -> None:
    statements = schema_privilege_statements()
    global_revoke = (
        "ALTER DEFAULT PRIVILEGES FOR ROLE ticketbox_owner "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;"
    )
    assert global_revoke in statements
    assert statements.index(global_revoke) < next(
        index
        for index, statement in enumerate(statements)
        if "GRANT EXECUTE ON FUNCTIONS TO ticketbox_runtime" in statement
    )

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

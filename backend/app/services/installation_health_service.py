"""Database readiness identity for the loopback installation probe."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


class InstallationDatabaseIdentityError(RuntimeError):
    """The connected database does not match this backend's configured store."""


def assert_installation_database_ready(db: Session, *, database_url: str) -> None:
    """Prove connectivity, configured DB/role identity, and initialized schema."""
    db.execute(select(func.set_config("statement_timeout", "1500ms", True)))
    database_name, role_name, schema_ready = db.execute(
        select(
            func.current_database(),
            func.current_user(),
            func.to_regclass("public.accounts").is_not(None),
        )
    ).one()
    configured = make_url(database_url)
    if (
        database_name != configured.database
        or role_name != configured.username
        or schema_ready is not True
    ):
        raise InstallationDatabaseIdentityError

"""DB migration owner-trap pre-flight guard (P1 model-invariant hardening).

The 2026-06-04 PostgreSQL cut-over loaded data as the ``postgres`` superuser,
leaving most tables owned by ``postgres`` while the app role had only DML; the
first ALTER migration was rejected ("must be owner") and startup silently
bricked for ~4 days (docs/runbook/POSTGRES_MIGRATION.md §3).
``_assert_role_can_alter_existing_schema`` turns that into a clear pre-flight
error before Alembic ``upgrade``.

These tests switch PostgreSQL roles (trust auth on the throwaway :5438 test
cluster) to exercise the block and the membership/ownership exemptions, so they
need real cross-connection commits (``real_db``; registered centrally in
conftest ``_PG_REAL_DB_NODES``). The ``real_db`` reset recreates every public
table owned by the connecting (superuser) role, which is the substrate for the
block case.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.database import _assert_role_can_alter_existing_schema
from app.database._core import settings

_GUARD_ROLE = "xpj_owner_preflight_role"


def _engine_as(role: str):
    """Engine connecting as ``role`` (trust auth → no password needed)."""
    url = make_url(settings.database_url).set(username=role)
    return create_engine(url)


@pytest.fixture
def guard_role():
    """A throwaway non-superuser LOGIN role with no relationship to the table
    owner — i.e. the cut-over trap victim role (DML only, cannot ALTER)."""
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP ROLE IF EXISTS "{_GUARD_ROLE}"'))
            conn.execute(text(f'CREATE ROLE "{_GUARD_ROLE}" LOGIN NOSUPERUSER'))
        yield _GUARD_ROLE
        with admin.connect() as conn:
            conn.execute(text(f'DROP ROLE IF EXISTS "{_GUARD_ROLE}"'))
    finally:
        admin.dispose()


def test_owner_preflight_blocks_role_without_membership(guard_role):
    """A role that is neither owner, owner-role member, nor superuser cannot
    ALTER the existing tables → guard must raise a clear, actionable error
    (this is exactly the cut-over owner trap)."""
    eng = _engine_as(guard_role)
    try:
        with eng.begin() as conn:
            assert conn.scalar(text("SELECT current_user")) == guard_role
            with pytest.raises(RuntimeError, match="表属主"):
                _assert_role_can_alter_existing_schema(conn)
    finally:
        eng.dispose()


def test_owner_preflight_allows_member_of_owner_role(guard_role):
    """Granting the role membership in the table-owner role lets it ALTER, so
    the guard must NOT raise — pins the ``pg_has_role(... 'MEMBER')`` exemption
    (delete that clause and this case starts raising)."""
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            owner = conn.scalar(
                text(
                    "SELECT tableowner FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename LIMIT 1"
                )
            )
            assert owner is not None and owner != guard_role
            conn.execute(text(f'GRANT "{owner}" TO "{guard_role}"'))
    finally:
        admin.dispose()

    eng = _engine_as(guard_role)
    try:
        with eng.begin() as conn:
            # No raise: the role now inherits the owner role.
            _assert_role_can_alter_existing_schema(conn)
    finally:
        eng.dispose()


def test_owner_preflight_allows_role_that_owns_the_tables():
    """The healthy / fresh-install shape: the connecting role owns every public
    table → zero flagged rows → no raise. The suite connects as that role."""
    eng = create_engine(settings.database_url)
    try:
        with eng.begin() as conn:
            _assert_role_can_alter_existing_schema(conn)
    finally:
        eng.dispose()

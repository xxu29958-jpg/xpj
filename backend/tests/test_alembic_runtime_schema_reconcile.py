from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from app.database import engine, load_alembic_context
from tests._infra.lane_policy import STATEFUL_POSTGRES_MARKS

pytestmark = STATEFUL_POSTGRES_MARKS

_CONSTRAINT = "ck_auth_tokens_scope_valid"
_PREVIOUS_REVISION = "20260630_0002"


def _auth_token_checks() -> dict[str, str]:
    return {
        str(item["name"]): str(item["sqltext"])
        for item in inspect(engine).get_check_constraints("auth_tokens")
        if item.get("name")
    }


def test_runtime_schema_reconcile_restores_auth_token_scope_check() -> None:
    assert "scope" in _auth_token_checks()[_CONSTRAINT]
    alembic = load_alembic_context()
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE auth_tokens DROP CONSTRAINT {_CONSTRAINT}")
        )
        connection.execute(
            text("UPDATE alembic_version SET version_num = :revision"),
            {"revision": _PREVIOUS_REVISION},
        )
        alembic.config.attributes["connection"] = connection
        command.upgrade(alembic.config, "head")

    checks = _auth_token_checks()
    assert _CONSTRAINT in checks
    assert "scope" in checks[_CONSTRAINT]
    assert "'app'" in checks[_CONSTRAINT]
    assert "'admin'" in checks[_CONSTRAINT]

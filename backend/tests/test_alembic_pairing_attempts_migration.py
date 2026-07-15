"""PostgreSQL round-trip for recoverable enrollment and server identity."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from alembic import command
from sqlalchemy import inspect, text

from app.database import Base, engine

_PREVIOUS_REVISION = "20260711_0001"
_EXPECTED_COLUMNS = {
    "id",
    "public_id",
    "pairing_code_id",
    "invitation_id",
    "account_id",
    "device_id",
    "ledger_id",
    "secret_hash",
    "session_token_hash",
    "session_expires_at",
    "session_soft_refresh_after",
    "expires_at",
    "last_issued_at",
    "created_at",
}
_IDENTITY_KEYS = ("server_id", "data_generation")
_REFRESH_COLUMNS = {
    "id",
    "public_id",
    "source_token_id",
    "replacement_token_id",
    "secret_hash",
    "expires_at",
    "last_issued_at",
    "created_at",
}


def _alembic_cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run_alembic(action, *args) -> None:
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _identity_values() -> dict[str, str]:
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT key, value FROM app_meta WHERE key IN ('server_id', 'data_generation')")
        ).all()
    return {str(key): str(value) for key, value in rows}


def _rule_actor_device_foreign_key() -> dict:
    return next(
        foreign_key
        for foreign_key in inspect(engine).get_foreign_keys("rule_application_batches")
        if foreign_key["constrained_columns"] == ["actor_device_id"]
    )


def _assert_enrollment_attempt_shape() -> None:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("device_enrollment_attempts")}
    assert set(columns) == _EXPECTED_COLUMNS
    assert columns["pairing_code_id"]["nullable"] is True
    assert columns["invitation_id"]["nullable"] is True
    assert columns["session_expires_at"]["nullable"] is True
    assert columns["session_soft_refresh_after"]["nullable"] is True
    assert all(
        not column["nullable"]
        for name, column in columns.items()
        if name
        not in {
            "pairing_code_id",
            "invitation_id",
            "session_expires_at",
            "session_soft_refresh_after",
        }
    )
    assert inspector.get_pk_constraint("device_enrollment_attempts")["constrained_columns"] == ["id"]

    indexes = {index["name"]: index for index in inspector.get_indexes("device_enrollment_attempts")}
    public_id_index = indexes["ix_device_enrollment_attempts_public_id"]
    assert public_id_index["unique"] is True
    assert public_id_index["column_names"] == ["public_id"]

    unique_constraints = {
        constraint["name"]: constraint for constraint in inspector.get_unique_constraints("device_enrollment_attempts")
    }
    assert unique_constraints["uq_device_enrollment_attempts_pairing_code_id"]["column_names"] == ["pairing_code_id"]
    assert unique_constraints["uq_device_enrollment_attempts_invitation_id"]["column_names"] == ["invitation_id"]
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("device_enrollment_attempts")}
    assert "ck_device_enrollment_attempts_one_source" in checks
    pairing_columns = {column["name"] for column in inspector.get_columns("pairing_codes")}
    assert "recovery_device_id" in pairing_columns
    pairing_fks = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("pairing_codes")
    }
    assert pairing_fks[("recovery_device_id",)]["options"]["ondelete"] == "CASCADE"
    enrollment_fks = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("device_enrollment_attempts")
    }
    assert enrollment_fks[("device_id",)]["options"]["ondelete"] == "CASCADE"


def _assert_session_refresh_attempt_shape() -> None:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("session_refresh_attempts")}
    assert set(columns) == _REFRESH_COLUMNS
    assert all(not column["nullable"] for column in columns.values())
    unique_constraints = {
        constraint["name"]: constraint for constraint in inspector.get_unique_constraints("session_refresh_attempts")
    }
    assert unique_constraints["uq_session_refresh_attempts_source_token_id"]["column_names"] == ["source_token_id"]
    assert unique_constraints["uq_session_refresh_attempts_replacement_token_id"]["column_names"] == [
        "replacement_token_id"
    ]
    foreign_keys = inspector.get_foreign_keys("session_refresh_attempts")
    assert {foreign_key["options"].get("ondelete") for foreign_key in foreign_keys} == {"CASCADE"}
    assert _rule_actor_device_foreign_key()["options"]["ondelete"] == "SET NULL"


def test_device_enrollment_and_server_identity_round_trip_on_postgres() -> None:
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    try:
        Base.metadata.create_all(bind=engine)
        actor_device_fk = _rule_actor_device_foreign_key()
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE session_refresh_attempts"))
            connection.execute(text("DROP TABLE device_enrollment_attempts"))
            connection.execute(text("ALTER TABLE pairing_codes DROP COLUMN recovery_device_id"))
            connection.execute(
                text('ALTER TABLE rule_application_batches DROP CONSTRAINT "' + str(actor_device_fk["name"]) + '"')
            )
            connection.execute(
                text(
                    "ALTER TABLE rule_application_batches "
                    "ADD CONSTRAINT rule_application_batches_actor_device_id_fkey "
                    "FOREIGN KEY (actor_device_id) REFERENCES devices (id)"
                )
            )
        _run_alembic(command.stamp, _PREVIOUS_REVISION)

        _run_alembic(command.upgrade, "head")
        _assert_enrollment_attempt_shape()
        _assert_session_refresh_attempt_shape()
        first_identity = _identity_values()
        assert set(first_identity) == set(_IDENTITY_KEYS)
        for value in first_identity.values():
            assert str(UUID(value)) == value

        _run_alembic(command.downgrade, _PREVIOUS_REVISION)
        assert "device_enrollment_attempts" not in _table_names()
        assert "session_refresh_attempts" not in _table_names()
        assert _rule_actor_device_foreign_key()["options"].get("ondelete") is None
        pairing_columns = {column["name"] for column in inspect(engine).get_columns("pairing_codes")}
        assert "recovery_device_id" not in pairing_columns
        assert _identity_values() == first_identity

        _run_alembic(command.upgrade, "head")
        _assert_enrollment_attempt_shape()
        _assert_session_refresh_attempt_shape()
        assert _identity_values() == first_identity
    finally:
        Base.metadata.drop_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

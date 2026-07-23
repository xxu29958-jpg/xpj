"""Regression tests for startup identity seeding tenant-id collection."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, MetaData, String, Table

from app.database import SessionLocal, engine
from app.database import _seed as seed_mod
from app.errors import DataIntegrityError


@pytest.mark.real_db
def test_collect_legacy_tenant_ids_uses_one_union_and_skips_missing_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = MetaData()
    first = Table("seed_identity_tenants_a", metadata, Column("tenant_id", String(64)))
    second = Table("seed_identity_tenants_b", metadata, Column("tenant_id", String(64)))

    class FirstModel:
        __tablename__ = first.name
        tenant_id = first.c.tenant_id

    class MissingModel:
        __tablename__ = "seed_identity_tenants_missing"
        tenant_id = first.c.tenant_id

    class SecondModel:
        __tablename__ = second.name
        tenant_id = second.c.tenant_id

    metadata.create_all(bind=engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                first.insert(),
                [
                    {"tenant_id": "owner"},
                    {"tenant_id": "owner"},
                    {"tenant_id": ""},
                    {"tenant_id": None},
                ],
            )
            connection.execute(
                second.insert(),
                [{"tenant_id": "family_a"}, {"tenant_id": "owner"}],
            )

        monkeypatch.setattr(
            seed_mod,
            "_tenant_scoped_models",
            lambda: (FirstModel, MissingModel, SecondModel),
        )

        with SessionLocal() as db:
            assert seed_mod._collect_legacy_tenant_ids(
                db,
                {first.name, second.name},
            ) == {"owner", "family_a"}
            assert seed_mod._collect_legacy_tenant_ids(db, set()) == set()
    finally:
        metadata.drop_all(bind=engine)


def test_seed_identity_data_validates_legacy_ids_before_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class FakeDb:
        committed = False

        def connection(self) -> object:
            return object()

        def commit(self) -> None:
            self.committed = True

    class FakeSession:
        db = FakeDb()

        def __enter__(self) -> FakeDb:
            return self.db

        def __exit__(self, *args: object) -> None:
            return None

    class FakeInspector:
        def get_table_names(self) -> list[str]:
            return ["expenses"]

    import app.services.identity_service as identity_service

    fake_session = FakeSession()
    monkeypatch.setattr(seed_mod, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(seed_mod, "inspect", lambda _connection: FakeInspector())
    monkeypatch.setattr(
        seed_mod,
        "_collect_legacy_tenant_ids",
        lambda _db, _existing: {"owner", "invalid tenant id"},
    )
    monkeypatch.setattr(
        identity_service,
        "ensure_identity_seed",
        lambda _db: calls.append("seed"),
    )
    monkeypatch.setattr(
        identity_service,
        "ensure_identity_for_existing_ledger_ids",
        lambda _db, ids: calls.append(("backfill", ids)),
    )

    with pytest.raises(DataIntegrityError, match="unsupported tenant_id"):
        seed_mod.seed_identity_data()

    assert calls == ["seed"]
    assert fake_session.db.committed is False

"""ADR-0049 P2: the Debt 母表 shape CHECK backstops actually REJECT malformed rows —
not merely exist (that's the alembic round-trip test). Proves the DB fails fast on the
counterparty / source shape invariants the service already maintains, so a future writer
producing e.g. a member Debt with no account, or a bill_split Debt with no source_id, is
stopped at the DB rather than storing a structurally-malformed obligation. ``ADD CONSTRAINT``
in the migration runs the same validation on existing PROD rows, so these also stand in for
"the migration fails fast on dirty data".

Each biconditional CHECK is exercised in BOTH directions (forward = the positive type
without its required field; reverse = the other type WITH the field it must not have), each
inside a ``begin_nested`` savepoint so the IntegrityError rolls back just that savepoint.
A real (FK-valid) account id is used for the "external WITH account" case so the CHECK —
not ``fk_debts_counterparty_account`` — is what fires.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Account, Debt
from tests.debt_proposal_helpers import (
    _create_external_debt,
    _create_member_debt,
    _mint_member_actor,
)


def _debt_id(public_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(Debt.id).where(Debt.public_id == public_id))


def _any_account_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))


def _expect_integrity_error(sql: str, params: dict) -> None:
    # begin_nested() is innermost so its __exit__ rolls the savepoint back and re-raises;
    # pytest.raises (one level out) then catches the re-raised IntegrityError.
    with SessionLocal() as db, pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(sql), params)
        db.flush()


def _member_debt(client: TestClient, identity) -> int:
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    return _debt_id(debt["public_id"])


def _external_debt(client: TestClient, identity) -> int:
    debt = _create_external_debt(client, identity.app_headers)
    return _debt_id(debt["public_id"])


# ── ck_debts_member_has_account ─────────────────────────────────────────────


def test_member_account_check_rejects_member_without_account(
    client: TestClient, *, identity
) -> None:
    # member with counterparty_account_id NULL violates ck_debts_member_has_account (forward).
    debt_id = _member_debt(client, identity)
    _expect_integrity_error(
        "UPDATE debts SET counterparty_account_id = NULL WHERE id = :i", {"i": debt_id}
    )


def test_member_account_check_rejects_external_with_account(
    client: TestClient, *, identity
) -> None:
    # external with a (FK-valid) counterparty_account_id violates ck_debts_member_has_account
    # (reverse) — the FK is satisfied, so the CHECK is what fires.
    debt_id = _external_debt(client, identity)
    _expect_integrity_error(
        "UPDATE debts SET counterparty_account_id = :a WHERE id = :i",
        {"a": _any_account_id(), "i": debt_id},
    )


# ── ck_debts_bill_split_has_source_id ───────────────────────────────────────


def test_bill_split_source_check_rejects_bill_split_without_source(
    client: TestClient, *, identity
) -> None:
    # a bill_split Debt with source_id NULL violates ck_debts_bill_split_has_source_id (forward).
    # (source_id NULL is uq_debts_source NULL-distinct, so the CHECK — not the unique — fires.)
    debt_id = _member_debt(client, identity)  # _create_member_debt seeds source_type='bill_split'
    _expect_integrity_error(
        "UPDATE debts SET source_id = NULL WHERE id = :i", {"i": debt_id}
    )


def test_bill_split_source_check_rejects_manual_with_source(
    client: TestClient, *, identity
) -> None:
    # a manual Debt carrying a source_id violates ck_debts_bill_split_has_source_id (reverse).
    debt_id = _external_debt(client, identity)  # _create_external_debt seeds source_type='manual'
    _expect_integrity_error(
        "UPDATE debts SET source_id = 'orphan-source' WHERE id = :i", {"i": debt_id}
    )

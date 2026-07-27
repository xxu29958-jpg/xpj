"""CSV batch apply × desktop bridge principal (218-E review).

``apply_csv_import_batch`` commits every row in its own transaction, so the
handler-entry revalidation (``_resolve_selected_ledger_id``) cannot cover a
batch mid-flight: the xact-level advisory lock dies with the first row
commit. When the caller passes the desktop bridge principal, the apply
revalidates it under the identity advisory lock before every row:

- a membership disable mid-batch aborts the remaining rows with 401 and the
  durable hard-revoke persists;
- a demotion to viewer aborts with 403 and honest inserted/remaining counts;
- a non-desktop caller (``desktop_session=None``) never revalidates.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import AuthToken, CsvImportBatch, CsvImportRow, Expense, LedgerMember
from app.services.csv_import_batch_service import _apply as apply_module
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
)
from app.services.time_service import now_utc
from tests.desktop_activation_support import token_row as _token_row
from tests.test_csv_import_batches_apply_lease import _csv_bytes
from tests.test_desktop_ledger_switch_prepare import _desktop_session
from tests.test_web_session_write_gate import _auth_context, _mint_desktop_session


def _seed_batch(*, row_count: int) -> tuple[str, int]:
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="desktop-revalidation.csv",
            file_obj=_csv_bytes(row_count),
        )
        return batch.public_id, batch.id


def _row_statuses(db, *, batch_id: int) -> list[str]:
    rows = db.scalars(
        select(CsvImportRow)
        .where(CsvImportRow.tenant_id == "owner")
        .where(CsvImportRow.batch_id == batch_id)
    ).all()
    return sorted(row.status for row in rows)


def _csv_expense_count(db) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        or 0
    )


def _update_membership(account_id: int, *, disable: bool) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id == account_id)
        )
        assert member is not None
        if disable:
            member.disabled_at = now_utc()
        else:
            member.role = "viewer"
        db.commit()


def _patch_first_row_then(monkeypatch, action) -> None:
    """Run ``action`` right after the first row's commit — the mid-batch window."""
    original = apply_module._apply_one_claimed_csv_import_row
    calls = {"count": 0}

    def wrapper(db, **kwargs):
        applied = original(db, **kwargs)
        calls["count"] += 1
        if calls["count"] == 1:
            action()
        return applied

    monkeypatch.setattr(apply_module, "_apply_one_claimed_csv_import_row", wrapper)


def test_desktop_apply_aborts_when_membership_disabled_mid_batch(identity, monkeypatch) -> None:
    token, account, device = _mint_desktop_session(ledger_id="owner", role="member")
    auth = _auth_context(token, account, device, ledger_id="owner", role="member")
    public_id, batch_id = _seed_batch(row_count=3)
    _patch_first_row_then(monkeypatch, lambda: _update_membership(account.id, disable=True))

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=3,
            desktop_session=auth,
        )
    assert exc.value.error == "invalid_token"
    assert exc.value.status_code == 401

    with SessionLocal() as db:
        # The durable hard-revoke persisted despite the outer rollback…
        stored = db.get(AuthToken, token.id)
        assert stored.revoked_at is not None
        assert stored.grace_until is None
        # …only the first row landed, and the remaining rows were reset to
        # valid so the batch stays retryable after a re-grant.
        assert _csv_expense_count(db) == 1
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "valid", "valid"]
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.public_id == public_id))
        assert batch.apply_token is None
        assert batch.status in {"parsed", "parsed_with_errors"}


def test_desktop_apply_aborts_with_counts_when_demoted_to_viewer_mid_batch(
    identity,
    monkeypatch,
) -> None:
    token, account, device = _mint_desktop_session(ledger_id="owner", role="member")
    auth = _auth_context(token, account, device, ledger_id="owner", role="member")
    public_id, batch_id = _seed_batch(row_count=3)
    _patch_first_row_then(monkeypatch, lambda: _update_membership(account.id, disable=False))

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=3,
            desktop_session=auth,
        )
    assert exc.value.error == "permission_denied"
    assert exc.value.status_code == 403
    assert "已导入 1 条" in exc.value.message
    assert "剩余 2 条" in exc.value.message

    with SessionLocal() as db:
        # A demotion is not a death: the bearer stays valid (read-only).
        stored = db.get(AuthToken, token.id)
        assert stored.revoked_at is None
        assert _csv_expense_count(db) == 1
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "valid", "valid"]


def test_desktop_apply_with_live_principal_applies_the_full_batch(identity) -> None:
    token, account, device = _mint_desktop_session(ledger_id="owner", role="member")
    auth = _auth_context(token, account, device, ledger_id="owner", role="member")
    public_id, batch_id = _seed_batch(row_count=3)

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=3,
            desktop_session=auth,
        )
    assert applied.inserted_count == 3
    assert applied.remaining_valid_rows == 0

    with SessionLocal() as db:
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "applied", "applied"]


def test_apply_without_desktop_session_never_revalidates(identity, monkeypatch) -> None:
    calls: list[int] = []

    def _spy(db, session_auth, *, mutation) -> str:
        calls.append(1)
        raise AssertionError("a non-desktop apply must not revalidate")

    monkeypatch.setattr(apply_module, "revalidate_desktop_session_under_lock", _spy)
    public_id, _batch_id = _seed_batch(row_count=2)

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=2,
        )
    assert applied.inserted_count == 2
    assert applied.remaining_valid_rows == 0
    assert calls == []


# ── API surface: a desktop bearer reaches /api/imports/csv (no platform gate) ──


def test_api_apply_desktop_bearer_applies_the_batch(identity, client: TestClient) -> None:
    """Reachability pin: a desktop-paired bearer (scope=app, platform=
    desktop) authenticates on the generic API surface and can drive the
    apply — so it needs the same per-row revalidation the /web bridge gets."""
    _, headers = _desktop_session(client, identity.pairing_code)
    public_id, _batch_id = _seed_batch(row_count=3)

    response = client.post(
        f"/api/imports/csv/{public_id}/apply",
        headers=headers,
        json={"batch_size": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["inserted_count"] == 3
    assert response.json()["remaining_valid_rows"] == 0


def test_api_apply_desktop_bearer_aborts_when_membership_disabled_mid_batch(
    identity,
    client: TestClient,
    monkeypatch,
) -> None:
    """The mid-batch window on the API surface: a membership disable landing
    after the first row commit must abort the remaining rows (401) with the
    durable revocation persisted."""
    _, headers = _desktop_session(client, identity.pairing_code)
    token_value = headers["Authorization"].removeprefix("Bearer ")
    account_id = _token_row(token_value).account_id
    public_id, batch_id = _seed_batch(row_count=3)
    _patch_first_row_then(monkeypatch, lambda: _update_membership(account_id, disable=True))

    response = client.post(
        f"/api/imports/csv/{public_id}/apply",
        headers=headers,
        json={"batch_size": 3},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"

    with SessionLocal() as db:
        stored = db.get(AuthToken, _token_row(token_value).id)
        assert stored.revoked_at is not None
        assert stored.grace_until is None
        assert _csv_expense_count(db) == 1
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "valid", "valid"]

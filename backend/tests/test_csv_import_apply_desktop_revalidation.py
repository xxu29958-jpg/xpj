"""CSV batch apply revalidates every network principal between row commits.

``apply_csv_import_batch`` commits every row in its own transaction, so the
handler-entry revalidation (``_resolve_selected_ledger_id``) cannot cover a
batch mid-flight: the xact-level advisory lock dies with the first row
commit. When the caller passes the desktop bridge principal, the apply
revalidates it under the identity advisory lock before every row:

- a membership disable mid-batch aborts the remaining rows with 401 and the
  durable hard-revoke persists;
- a demotion to viewer aborts with 403 and honest inserted/remaining counts;
- ordinary App/Web principals use the shared identity and membership validator;
- internal/loopback callers without a session do not use desktop revalidation.
"""

from __future__ import annotations

import pytest
from _web_native_form_support import hidden_post_forms
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import AuthToken, CsvImportBatch, CsvImportRow, Device, Expense, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.csv_import_batch_service import _apply as apply_module
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
)
from app.services.identity_service import hash_secret, new_session_token
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.time_service import now_utc
from tests._infra.csv import _csv_bytes
from tests._runtime_protocol import current_protocol_headers
from tests._web_public_session_support import public_client
from tests.desktop_activation_support import _auth_context, _desktop_session, _mint_desktop_session


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
            initiator_account_id=auth.account_id,
            initiator_device_id=auth.device_id,
            public_id=public_id,
            batch_size=3,
            session_auth=auth,
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
            initiator_account_id=auth.account_id,
            initiator_device_id=auth.device_id,
            public_id=public_id,
            batch_size=3,
            session_auth=auth,
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
            initiator_account_id=auth.account_id,
            initiator_device_id=auth.device_id,
            public_id=public_id,
            batch_size=3,
            session_auth=auth,
        )
    assert applied.inserted_count == 3
    assert applied.remaining_valid_rows == 0

    with SessionLocal() as db:
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "applied", "applied"]


def test_internal_apply_without_session_does_not_use_desktop_revalidation(identity, monkeypatch) -> None:
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
            initiator_account_id=find_owner_account_id_for_ledger(db, ledger_id="owner"),
            initiator_device_id=None,
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
        headers=current_protocol_headers(headers),
        json={"batch_size": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["inserted_count"] == 3
    assert response.json()["remaining_valid_rows"] == 0


@pytest.mark.real_db
@pytest.mark.parametrize("platform", ["desktop", "android", "web"])
@pytest.mark.parametrize("disable", [False, True], ids=["demote-viewer", "disable-member"])
def test_apply_stops_on_revocation_and_resumes_original_rows_without_duplicates(
    identity,
    client: TestClient,
    monkeypatch,
    request,
    platform,
    disable,
) -> None:
    token, account, device = _mint_desktop_session(ledger_id="owner", role="member")
    token_value = new_session_token()
    with SessionLocal() as db:
        db.get(Device, device.id).platform = platform
        db.get(AuthToken, token.id).token_hash = hash_secret(token_value)
        db.commit()
    public_id, batch_id = _seed_batch(row_count=3)
    _patch_first_row_then(monkeypatch, lambda: _update_membership(account.id, disable=disable))
    original_form = None
    if platform == "web":
        client = public_client()
        request.addfinalizer(client.close)

    def apply():
        nonlocal original_form
        if platform != "web":
            return client.post(f"/api/imports/csv/{public_id}/apply",
                headers=current_protocol_headers({"Authorization": f"Bearer {token_value}"}),
                json={"batch_size": 3})
        client.cookies.set(SESSION_COOKIE_NAME, token_value)
        action = f"/web/import/{public_id}/apply"
        if original_form is None:
            page = client.get(f"/web/import/{public_id}?ledger_id=owner")
            assert page.status_code == 200, page.text
            original_form = hidden_post_forms(page.text)[action]
        return client.post(action, data=original_form,
            headers={"Origin": str(client.base_url).rstrip("/")}, follow_redirects=False)

    response = apply()
    if platform == "web":
        assert response.status_code == 303
        assert "flash_type=error" in response.headers["location"]
    else:
        assert response.status_code in {401, 403}, response.text

    with SessionLocal() as db:
        stored = db.get(AuthToken, token.id)
        if platform == "desktop" and disable:
            assert stored.revoked_at is not None
            assert stored.grace_until is None
        assert _csv_expense_count(db) == 1
        assert _row_statuses(db, batch_id=batch_id) == ["applied", "valid", "valid"]
        first_id = db.scalar(select(Expense.id).where(Expense.source == "CSV导入"))
        batch = db.get(CsvImportBatch, batch_id)
        assert batch.apply_token is None
        member = db.scalar(select(LedgerMember).where(
            LedgerMember.ledger_id == "owner", LedgerMember.account_id == account.id))
        member.role = "member"
        member.disabled_at = None
        if stored.revoked_at is not None:
            # Re-enrollment creates a new credential; never resurrect the revoked one.
            token_value = new_session_token()
            db.add(AuthToken(token_hash=hash_secret(token_value), account_id=account.id,
                device_id=device.id, ledger_id="owner", scope="app"))
        db.commit()

    resumed = apply()
    assert resumed.status_code == (303 if platform == "web" else 200), resumed.text
    if platform != "web":
        assert resumed.json()["inserted_count"] == 2
    replayed = apply()
    assert replayed.status_code == (303 if platform == "web" else 200), replayed.text
    if platform != "web":
        assert replayed.json()["inserted_count"] == 0
    with SessionLocal() as db:
        assert _csv_expense_count(db) == 3
        assert _row_statuses(db, batch_id=batch_id) == ["applied"] * 3
        assert db.get(Expense, first_id) is not None

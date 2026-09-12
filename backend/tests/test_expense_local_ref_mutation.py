"""Issue #65 slice 3 — route accepts ``server-id`` or ``local:{client_ref}`` +
the OCC first-write path.

The expense mutation routes take a string ref and funnel it
through ``resolve_expense_for_mutation``. The dangerous part is OCC: a
``local:{client_ref}`` that resolves to an already-synced server row, sent by a
client that never saw the server ``row_version`` (the response-lost / first-write
case), uses its original accepted creation basis; a later writer and the normal
server-id OCC path must still 409. These tests prove the two paths are orthogonal.

``# coverage: auth-401`` — no-auth coverage for these routes lives in the existing
per-route auth tests; this file is the local-ref + OCC matrix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, ApiIdempotencyKey, AuthToken, Device, Expense
from app.services.expense_query import local_ref_storage_key
from app.services.identity_service import hash_secret, new_session_token
from tests._runtime_protocol import current_protocol_headers

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


def _create_local_expense(
    client: TestClient,
    headers: dict[str, str],
    **overrides,
) -> dict:
    body = {
        "home_currency_code": "CNY",
        "amount_cents": 1500,
        "merchant": "本地引用",
        "category": "餐饮",
        "expense_time": "2026-05-05T00:00:00Z",
    }
    body.update(overrides)
    resp = client.post("/api/expenses/manual", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"
    return resp.json()


def _row_version(client: TestClient, server_id: int, *, identity: TestIdentity) -> int:
    resp = client.get(f"/api/expenses/{server_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["row_version"]


def _owner_device_id(identity: TestIdentity) -> int:
    with SessionLocal() as db:
        tok = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(identity.app_token))
            .one()
        )
        return tok.device_id


def _second_owner_device_token() -> str:
    """A second device paired into the SAME ``owner`` ledger (a different
    ``device_id``), so a cross-DEVICE (not cross-tenant) miss can be exercised at
    the route layer — the device namespace comes from the token, not the body."""
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        device = Device(account_id=owner.id, device_name="pytest-android-2", platform="android")
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=owner.id,
                device_id=device.id,
                ledger_id="owner",
                scope="app",
            )
        )
        db.commit()
        return token


def _correct(client, ref, *, version, key, headers, merchant):
    return client.post(
        f"/api/expenses/{ref}/corrections",
        headers={**headers, "Idempotency-Key": key},
        json={
            "merchant": merchant,
            "reason": "本地引用更正测试",
            "expected_row_version": version,
        },
    )


# ── local-ref first write (the slice-3 danger path) ─────────────────────────


def test_local_ref_first_write_succeeds_no_false_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A ``local:{ref}`` mutation carrying the first-write sentinel (0) — the
    client never saw the server row_version — applies to its accepted creation
    basis without guessing from current state."""
    _create_local_expense(client, identity.app_headers, client_ref="fw-1")

    resp = _correct(
        client, "local:fw-1", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="首写",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["expense"]["merchant"] == "首写"


def test_local_ref_first_write_refuses_a_later_current_row_version(
    client: TestClient, identity: TestIdentity
) -> None:
    """A later edit is a real conflict with the unobserved original creation basis."""
    created = _create_local_expense(client, identity.app_headers, client_ref="fw-2")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    bumped = _correct(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="先抬版本",
    )
    assert bumped.status_code == 201, bumped.text
    v1 = bumped.json()["expense"]["row_version"]
    assert v1 != v0

    first_write = _correct(
        client, "local:fw-2", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="本地首写到当前版本",
    )
    assert first_write.status_code == 409, first_write.text
    assert first_write.json()["error"] == "state_conflict"
    current = client.get(f"/api/expenses/{server_id}", headers=identity.app_headers)
    assert (current.json()["merchant"], current.json()["row_version"]) == ("先抬版本", v1)


def test_local_ref_resolves_same_row_as_server_id(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local-ref edit is visible when the same row is read by server id —
    proving the ref resolves to the very same row."""
    created = _create_local_expense(client, identity.app_headers, client_ref="same-row")
    server_id = created["id"]

    resp = _correct(
        client, "local:same-row", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="本地改的",
    )
    assert resp.status_code == 201, resp.text

    by_id = client.get(f"/api/expenses/{server_id}", headers=identity.app_headers)
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["merchant"] == "本地改的"


def test_local_ref_first_write_replay_returns_canonical(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.6 still holds on the local-ref path: replaying the SAME key + SAME
    sentinel re-serialises the canonical row (201) without re-applying — even
    though the current row_version drifted after the first write."""
    _create_local_expense(client, identity.app_headers, client_ref="replay")
    key = str(uuid4())

    first = _correct(
        client, "local:replay", version=0, key=key,
        headers=identity.app_headers, merchant="一次",
    )
    assert first.status_code == 201, first.text
    v1 = first.json()["expense"]["row_version"]

    replay = _correct(
        client, "local:replay", version=0, key=key,
        headers=identity.app_headers, merchant="一次",
    )
    assert replay.status_code == 201, replay.text  # NOT 409, NOT a fingerprint mismatch
    assert replay.json()["expense"]["row_version"] == v1, "a HIT must re-serialise, not re-bump"


# ── orthogonality: OCC still enforced for genuine conflicts ─────────────────


def test_local_ref_and_server_id_paths_are_orthogonal(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local-ref first-write does NOT disable OCC: a stale server-id write
    still 409s, and a correctly-versioned one still succeeds."""
    created = _create_local_expense(client, identity.app_headers, client_ref="orth")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    # (A) local-ref first-write applies to the original accepted basis → bumps the row.
    a = _correct(
        client, "local:orth", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="A",
    )
    assert a.status_code == 201, a.text
    v_after = a.json()["expense"]["row_version"]
    assert v_after != v0

    # (B) a genuine concurrent writer holding the now-stale v0 still 409s.
    b = _correct(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="B",
    )
    assert b.status_code == 409, b.text
    assert b.json()["error"] == "state_conflict"

    # (C) the correctly-versioned server-id write proceeds.
    c = _correct(
        client, server_id, version=v_after, key=str(uuid4()),
        headers=identity.app_headers, merchant="C",
    )
    assert c.status_code == 201, c.text
    assert c.json()["expense"]["merchant"] == "C"


def test_server_id_with_sentinel_zero_is_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A SERVER-id ref is never first-write: the sentinel 0 is not special-cased,
    so its CAS finds no row at version 0 (real rows start at 1) → 409. A synced
    row must not be blind-written."""
    created = _create_local_expense(client, identity.app_headers, client_ref="no-blind")
    server_id = created["id"]

    resp = _correct(
        client, server_id, version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="盲写",
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "state_conflict"


def test_server_id_string_path_still_works(
    client: TestClient, identity: TestIdentity
) -> None:
    """Backward compat: the widened (str) path param still resolves a plain
    numeric server-id ref exactly as before."""
    created = _create_local_expense(client, identity.app_headers, client_ref="compat")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    resp = _correct(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="老路径",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["expense"]["merchant"] == "老路径"


# ── miss / malformed refs → 404 ─────────────────────────────────────────────


def test_unknown_local_ref_returns_404(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local ref this device never created resolves to nothing → 404."""
    resp = _correct(
        client, "local:never-created", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="不存在",
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "expense_not_found"


def test_malformed_ref_returns_404(
    client: TestClient, identity: TestIdentity
) -> None:
    """A non-numeric, non-``local:`` ref is a malformed id → 404 (not a 500 from
    ``int()``)."""
    resp = _correct(
        client, "not-a-ref", version=1, key=str(uuid4()),
        headers=identity.app_headers, merchant="畸形",
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "expense_not_found"


def test_cross_device_local_ref_miss_returns_404(
    client: TestClient, identity: TestIdentity
) -> None:
    """The device namespace is enforced at the route: device B (same ledger,
    different ``device_id``) cannot reach device A's not-yet-synced local ref."""
    _create_local_expense(client, identity.app_headers, client_ref="device-a-ref")
    device_b_token = _second_owner_device_token()
    device_b_headers = current_protocol_headers({"Authorization": f"Bearer {device_b_token}"})

    resp = _correct(
        client, "local:device-a-ref", version=0, key=str(uuid4()),
        headers=device_b_headers, merchant="别的设备",
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "expense_not_found"


# ── explicit-version route (confirm) threads the same way ────────────────────


def test_confirm_via_local_ref_resolves(
    client: TestClient, identity: TestIdentity
) -> None:
    """An explicit-version route (confirm) also resolves a local ref. A manual
    expense is already ``confirmed``, so confirm is idempotent (200) — proving
    the ref resolved (a miss would 404)."""
    _create_local_expense(
        client,
        identity.app_headers,
        client_ref="confirm-ref",
    )

    resp = client.post(
        "/api/expenses/local:confirm-ref/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0},
    )
    assert resp.status_code == 200, resp.text


def _create_confirmable_pending_local_ref(client, identity, *, client_ref):
    """Saving a rate does not replace the accepted pending creation receipt."""
    body = {
        "client_ref": client_ref, "home_currency_code": "CNY", "original_currency": "JPY",
        "original_amount": "300", "merchant": "本地确认", "category": "餐饮",
        "expense_time": "2026-05-05T00:00:00Z"}
    pending = client.post("/api/expenses/manual", headers=identity.app_headers, json=body)
    assert pending.status_code == 200, pending.text
    assert (pending.json()["status"], pending.json()["amount_cents"]) == ("pending", None)
    rate = client.put("/api/exchange-rates/JPY/2026-05-05",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "currency_code": "JPY", "home_currency_code": "CNY", "rate_date": "2026-05-05",
            "rate_to_cny": "0.05", "source": "manual", "expected_row_version": 0})
    assert rate.status_code == 200, rate.text
    return pending.json(), body


def test_confirm_via_local_ref_first_write_runs_cas(
    client: TestClient, identity: TestIdentity
) -> None:
    """First-write CAS converts the original pending basis; confirmation needs review."""
    device_id = _owner_device_id(identity)
    pending, creation_body = _create_confirmable_pending_local_ref(client, identity, client_ref="confirm-fw")
    url = "/api/expenses/local:confirm-fw"
    original_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}

    refused = client.post(f"{url}/confirm", headers=original_headers, json={"expected_row_version": 0})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "exchange_rate_pending"
    assert _row_version(client, pending["id"], identity=identity) == pending["row_version"]

    edit_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    edit_body = {"expected_row_version": 0, "original_currency_code": "JPY", "original_amount_minor": 300}
    saved = client.patch(url, headers=edit_headers, json=edit_body)
    assert saved.status_code == 200, saved.text
    converted = saved.json()
    assert (converted["status"], converted["fx_status"], converted["amount_cents"]) == ("pending", "ready", 1500)
    assert converted["row_version"] > pending["row_version"]
    replay_edit = client.patch(url, headers=edit_headers, json=edit_body)
    assert replay_edit.status_code == 200, replay_edit.text
    assert replay_edit.json()["row_version"] == converted["row_version"]

    stale = client.post(f"{url}/confirm", headers=original_headers, json={"expected_row_version": 0})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"
    reviewed = client.get(f"/api/expenses/{pending['id']}", headers=identity.app_headers)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["row_version"] == converted["row_version"]
    assert reviewed.json()["amount_cents"] == 1500 and reviewed.json()["status"] == "pending"

    confirm_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    confirm_body = {"expected_row_version": reviewed.json()["row_version"]}
    resp = client.post(f"{url}/confirm", headers=confirm_headers, json=confirm_body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["row_version"] > converted["row_version"]
    replay_confirm = client.post(f"{url}/confirm", headers=confirm_headers, json=confirm_body)
    assert replay_confirm.status_code == 200, replay_confirm.text
    assert replay_confirm.json()["row_version"] == resp.json()["row_version"]
    creation_replay = client.post("/api/expenses/manual", headers=identity.app_headers, json=creation_body)
    assert creation_replay.status_code == 200, creation_replay.text
    assert {key: creation_replay.json()[key] for key in ("id", "status", "amount_cents", "row_version")} == {
        key: pending[key] for key in ("id", "status", "amount_cents", "row_version")}
    with SessionLocal() as db:
        exp = (
            db.query(Expense)
            .filter(Expense.draft_idempotency_key == local_ref_storage_key(device_id, "confirm-fw"))
            .one()
        )
        assert exp.status == "confirmed", "effective version reached confirm's CAS"


def test_confirm_unknown_local_ref_returns_404(
    client: TestClient, identity: TestIdentity
) -> None:
    """The route-level resolve 404s for explicit-version routes too."""
    resp = client.post(
        "/api/expenses/local:nope/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "expense_not_found"


def test_fresh_local_mutation_without_original_receipt_cannot_claim_unknown_basis(client, identity):
    created = _create_local_expense(client, identity.app_headers, client_ref="legacy-no-receipt")
    with SessionLocal() as db:
        claim = db.query(ApiIdempotencyKey).filter(ApiIdempotencyKey.operation == "create_manual_expense").one()
        db.delete(claim)
        db.commit()
    refused = _correct(client, "local:legacy-no-receipt", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="Cannot assume latest")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "state_conflict"
    current = client.get(f"/api/expenses/{created['id']}", headers=identity.app_headers)
    assert current.json()["merchant"] == created["merchant"]
    assert current.json()["row_version"] == created["row_version"]

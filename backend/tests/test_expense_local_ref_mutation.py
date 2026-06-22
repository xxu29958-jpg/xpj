"""Issue #65 slice 3 — route accepts ``server-id`` or ``local:{client_ref}`` +
the OCC first-write path.

The 9 outbox-routed expense mutation routes now take a string ref and funnel it
through ``resolve_expense_for_mutation``. The dangerous part is OCC: a
``local:{client_ref}`` that resolves to an already-synced server row, sent by a
client that never saw the server ``row_version`` (the response-lost / first-write
case), must NOT false-409 — yet a genuine concurrent writer and the normal
server-id OCC path must still 409. These tests prove the two paths are orthogonal.

``# coverage: auth-401`` — no-auth coverage for these routes lives in the existing
per-route auth tests; this file is the local-ref + OCC matrix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Expense
from app.services.expense_query import local_ref_storage_key
from app.services.identity_service import hash_secret, new_session_token

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


def _create_manual(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "amount_cents": 1500,
        "merchant": "本地引用",
        "category": "餐饮",
        "expense_time": "2026-05-05T00:00:00Z",
    }
    body.update(overrides)
    resp = client.post("/api/expenses/manual", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
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


def _patch(client, ref, *, version, key, headers, merchant):
    return client.patch(
        f"/api/expenses/{ref}",
        headers={**headers, "Idempotency-Key": key},
        json={"merchant": merchant, "expected_row_version": version},
    )


# ── local-ref first write (the slice-3 danger path) ─────────────────────────


def test_local_ref_first_write_succeeds_no_false_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A ``local:{ref}`` mutation carrying the first-write sentinel (0) — the
    client never saw the server row_version — applies to the current row instead
    of false-409-ing."""
    _create_manual(client, identity.app_headers, client_ref="fw-1")

    resp = _patch(
        client, "local:fw-1", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="首写",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["merchant"] == "首写"


def test_local_ref_first_write_applies_to_current_row_version(
    client: TestClient, identity: TestIdentity
) -> None:
    """The sentinel reads the CURRENT row_version, not an assumed 1: after a
    server-id edit bumps the row, a local-ref first-write still lands (no false
    409)."""
    created = _create_manual(client, identity.app_headers, client_ref="fw-2")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    bumped = _patch(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="先抬版本",
    )
    assert bumped.status_code == 200, bumped.text
    v1 = bumped.json()["row_version"]
    assert v1 != v0

    first_write = _patch(
        client, "local:fw-2", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="本地首写到当前版本",
    )
    assert first_write.status_code == 200, first_write.text
    assert first_write.json()["merchant"] == "本地首写到当前版本"
    assert first_write.json()["row_version"] != v1, "the first-write CAS must still bump"


def test_local_ref_resolves_same_row_as_server_id(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local-ref edit is visible when the same row is read by server id —
    proving the ref resolves to the very same row."""
    created = _create_manual(client, identity.app_headers, client_ref="same-row")
    server_id = created["id"]

    resp = _patch(
        client, "local:same-row", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="本地改的",
    )
    assert resp.status_code == 200, resp.text

    by_id = client.get(f"/api/expenses/{server_id}", headers=identity.app_headers)
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["merchant"] == "本地改的"


def test_local_ref_first_write_replay_returns_canonical(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.6 still holds on the local-ref path: replaying the SAME key + SAME
    sentinel re-serialises the canonical row (200) without re-applying — even
    though the current row_version drifted after the first write."""
    _create_manual(client, identity.app_headers, client_ref="replay")
    key = str(uuid4())

    first = _patch(
        client, "local:replay", version=0, key=key,
        headers=identity.app_headers, merchant="一次",
    )
    assert first.status_code == 200, first.text
    v1 = first.json()["row_version"]

    replay = _patch(
        client, "local:replay", version=0, key=key,
        headers=identity.app_headers, merchant="一次",
    )
    assert replay.status_code == 200, replay.text  # NOT 409, NOT a fingerprint mismatch
    assert replay.json()["row_version"] == v1, "a HIT must re-serialise, not re-bump"


# ── orthogonality: OCC still enforced for genuine conflicts ─────────────────


def test_local_ref_and_server_id_paths_are_orthogonal(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local-ref first-write does NOT disable OCC: a stale server-id write
    still 409s, and a correctly-versioned one still 200s."""
    created = _create_manual(client, identity.app_headers, client_ref="orth")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    # (A) local-ref first-write applies to current → bumps the row.
    a = _patch(
        client, "local:orth", version=0, key=str(uuid4()),
        headers=identity.app_headers, merchant="A",
    )
    assert a.status_code == 200, a.text
    v_after = a.json()["row_version"]
    assert v_after != v0

    # (B) a genuine concurrent writer holding the now-stale v0 still 409s.
    b = _patch(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="B",
    )
    assert b.status_code == 409, b.text
    assert b.json()["error"] == "state_conflict"

    # (C) the correctly-versioned server-id write proceeds.
    c = _patch(
        client, server_id, version=v_after, key=str(uuid4()),
        headers=identity.app_headers, merchant="C",
    )
    assert c.status_code == 200, c.text
    assert c.json()["merchant"] == "C"


def test_server_id_with_sentinel_zero_is_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A SERVER-id ref is never first-write: the sentinel 0 is not special-cased,
    so its CAS finds no row at version 0 (real rows start at 1) → 409. A synced
    row must not be blind-written."""
    created = _create_manual(client, identity.app_headers, client_ref="no-blind")
    server_id = created["id"]

    resp = _patch(
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
    created = _create_manual(client, identity.app_headers, client_ref="compat")
    server_id = created["id"]
    v0 = _row_version(client, server_id, identity=identity)

    resp = _patch(
        client, server_id, version=v0, key=str(uuid4()),
        headers=identity.app_headers, merchant="老路径",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["merchant"] == "老路径"


# ── miss / malformed refs → 404 ─────────────────────────────────────────────


def test_unknown_local_ref_returns_404(
    client: TestClient, identity: TestIdentity
) -> None:
    """A local ref this device never created resolves to nothing → 404."""
    resp = _patch(
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
    resp = _patch(
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
    _create_manual(client, identity.app_headers, client_ref="device-a-ref")
    device_b_token = _second_owner_device_token()
    device_b_headers = {"Authorization": f"Bearer {device_b_token}"}

    resp = _patch(
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
    _create_manual(client, identity.app_headers, client_ref="confirm-ref")

    resp = client.post(
        "/api/expenses/local:confirm-ref/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0},
    )
    assert resp.status_code == 200, resp.text


def _force_pending(client_ref: str, *, device_id: int) -> None:
    """Flip a manual (born ``confirmed``) expense to ``pending`` so an
    explicit-version route actually REACHES its OCC CAS (a plain status set does
    not bump row_version)."""
    with SessionLocal() as db:
        exp = (
            db.query(Expense)
            .filter(Expense.draft_idempotency_key == local_ref_storage_key(device_id, client_ref))
            .one()
        )
        exp.status = "pending"
        db.commit()


def test_confirm_via_local_ref_first_write_runs_cas(
    client: TestClient, identity: TestIdentity
) -> None:
    """An explicit-version route threads the EFFECTIVE version (not the raw
    sentinel) into its CAS. confirm short-circuits a ``confirmed`` row before the
    CAS, so this drives a ``pending`` row: a local-ref first-write (sentinel 0)
    confirms it. Were confirm to pass the raw sentinel 0, its CAS
    (``WHERE row_version == 0``) would rowcount-0 → 409; asserting it confirms
    proves the effective-version threading for the explicit-version family (only
    PATCH uses ``payload.model_copy``)."""
    device_id = _owner_device_id(identity)
    _create_manual(client, identity.app_headers, client_ref="confirm-fw")
    _force_pending("confirm-fw", device_id=device_id)

    resp = client.post(
        "/api/expenses/local:confirm-fw/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0},
    )
    assert resp.status_code == 200, resp.text
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
